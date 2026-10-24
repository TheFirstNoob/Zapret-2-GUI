from __future__ import annotations

import hmac
import json
import threading
from http import HTTPStatus
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse, parse_qs

from core.config import ConfigManager
from core.zapret_controller import ZapretController
from core.tester import Zapret2Tester
from server.app_state import (STATE, get_root_dir, probe_debug as _probe_debug)
from server import (api_blobs, api_cdn, api_config, api_contested,
                    api_control, api_diag, api_games, api_info, api_lists,
                    api_probe, api_reports, api_service, api_tester,
                    api_update, api_zapret1, session_recovery)


CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js":  "application/javascript; charset=utf-8",
    ".json":"application/json; charset=utf-8",
    ".ico": "image/x-icon",
    ".png": "image/png",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".woff2":"font/woff2",
}


# Лимит тела POST: локальный сервер, но бесконечное тело - это DoS
# собственного GUI (ревью 18.10). 16 МиБ покрывает импорт настроек.
MAX_BODY_BYTES = 16 * 1024 * 1024


# ── JS-бандл (аудит #2) ──────────────────────────────────────
# app.js собран из частей frontend/js/app/*.js; склейка - НА СЕРВЕРЕ (единый
# <script src="js/app.js">; ES-модули нельзя - глобальный скоуп и inline
# onclick). Порядок фиксирован, все части обязательны. Порезка проверена
# байт-в-байт: b"\n".join(parts) == исходный app.js (sha256 совпадал).
_JS_BUNDLE_PARTS = (
    "app/00_utils.js", "app/10_status.js", "app/20_app.js", "app/30_main.js",
    "app/40_diagnostics.js", "app/50_games.js", "app/55_appinfo.js",
    "app/60_lists.js", "app/70_cdn.js", "app/75_asn.js", "app/80_tester.js",
    "app/90_ui_boot.js",
)


def _js_bundle_bytes(frontend: Path) -> bytes:
    """Склейка частей бандла в единый JS (источник - js/app.js URL)."""
    parts = []
    for rel in _JS_BUNDLE_PARTS:
        parts.append((frontend / "js" / rel).read_bytes())
    return b"\n".join(parts)


def _js_bundle_mtime(frontend: Path) -> float:
    """Самая свежая mtime частей - кэш-бастер WebView2 (замена mtime app.js)."""
    newest = 0.0
    for rel in _JS_BUNDLE_PARTS:
        newest = max(newest, (frontend / "js" / rel).stat().st_mtime)
    return newest


# ── Таблицы маршрутов (аудит #1, Inc C завершён) ─────────────
# path -> (цель, спец-аргументы). Цель - функция api_*(ctx, ...) -> dict
# (или ApiError); "@ctx"/"@params"/"@data" подставляют контекст/query/тело
# в порядке перечисления. В классе остались только транспорт и статика
# (_handle_index/_handle_static); доменные хендлеры живут в api_*.py.

_GET_ROUTES: dict[str, tuple] = {
    "/": ("_handle_index", ("@params",)),
    "/api/diagnose/status": (api_diag.diagnose_status, ("@ctx",)),
    "/api/config": (api_config.get_config, ("@ctx",)),
    "/api/version": (api_info.version, ("@ctx",)),
    "/api/app-info": (api_info.app_info, ("@ctx",)),
    "/api/status": (api_info.status, ("@ctx",)),
    "/api/profiles": (api_info.list_profiles, ("@ctx",)),
    "/api/exclude-list": (api_lists.get_list, ("@ctx", "list-exclude-user.txt")),
    "/api/include-list": (api_lists.get_list, ("@ctx", "list-include-user.txt")),
    "/api/bundled-domains": (api_lists.bundled_domains, ("@ctx",)),
    "/api/fake-blobs": (api_blobs.fake_blobs, ("@ctx",)),
    # USER-файл: lists/ipset-exclude.txt — СИСТЕМНЫЙ список (приватные
    # диапазоны), его не редактируем из GUI (решение автора,
    # REVIEW_VERDICT.md §2.9). Движок учитывает ipset-exclude-user.txt
    # вторым --ipset-exclude (core/launcher.py).
    "/api/ipset-exclude-list": (api_lists.get_list, ("@ctx", "ipset-exclude-user.txt")),
    "/api/ipset-include-list": (api_lists.get_list, ("@ctx", "ipset-include-user.txt")),
    "/api/lists/health": (api_lists.lists_health, ("@ctx",)),
    "/api/contested/status": (api_contested.contested_status, ("@ctx",)),
    "/api/service/status": (api_service.service_status, ("@ctx",)),
    "/api/zapret1/strategies": (api_zapret1.zapret1_strategies, ("@ctx",)),
    "/api/tester/status": (api_tester.tester_status, ("@ctx",)),
    "/api/update-check": (api_update.update_check, ("@ctx", "@params")),
    "/api/update/status": (api_update.update_status, ("@ctx",)),
    "/api/process-probe/status": (api_probe.probe_status, ("@ctx",)),
    "/api/games": (api_games.games_get, ("@ctx",)),
}

_POST_ROUTES: dict[str, tuple] = {
    "/api/config": (api_config.save_config, ("@ctx", "@data")),
    "/api/zapret1/save-dir": (api_zapret1.zapret1_save_dir, ("@ctx", "@data")),
    "/api/zapret1/start": (api_zapret1.zapret1_start, ("@ctx", "@data")),
    "/api/zapret1/stop": (api_zapret1.zapret1_stop, ("@ctx",)),
    "/api/start": (api_control.start_zapret, ("@ctx", "@data")),
    "/api/stop": (api_control.stop_zapret, ("@ctx",)),
    "/api/exclude-list": (api_lists.save_list, ("@ctx", "@data", "list-exclude-user.txt")),
    "/api/include-list": (api_lists.save_list, ("@ctx", "@data", "list-include-user.txt")),
    # USER-файл (см. GET выше): системный ipset-exclude.txt из GUI не правим.
    "/api/ipset-exclude-list": (api_lists.save_list, ("@ctx", "@data", "ipset-exclude-user.txt")),
    "/api/ipset-include-list": (api_lists.save_list, ("@ctx", "@data", "ipset-include-user.txt")),
    "/api/contested/toggle": (api_contested.contested_toggle, ("@ctx", "@data")),
    "/api/contested/check": (api_contested.contested_check, ("@ctx", "@data")),
    "/api/lists/dedupe": (api_lists.lists_dedupe, ("@ctx",)),
    "/api/lists/add-domain": (api_lists.lists_add_domain, ("@ctx", "@data")),
    "/api/service/install": (api_service.service_install, ("@ctx", "@data")),
    "/api/service/remove": (api_service.service_remove, ("@ctx",)),
    "/api/service/start": (api_service.service_start, ("@ctx", "@data")),
    "/api/service/stop": (api_service.service_stop, ("@ctx",)),
    "/api/service/repair": (api_service.service_repair, ("@ctx",)),
    "/api/diagnose/action": (api_diag.diagnose_action, ("@ctx", "@data")),
    "/api/diagnose/status": (api_diag.diagnose_status, ("@ctx",)),
    "/api/export-report": (api_reports.export_report, ("@ctx", "@data")),
    "/api/asn-scan": (api_tester.asn_scan, ("@ctx", "@data")),
    "/api/blob-probe": (api_blobs.blob_probe, ("@ctx", "@data")),
    "/api/tester/action": (api_tester.tester_action, ("@ctx", "@data")),
    "/api/update/start": (api_update.update_start, ("@ctx",)),
    "/api/update/apply": (api_update.update_apply, ("@ctx",)),
    "/api/settings/export": (api_config.settings_export, ("@ctx",)),
    "/api/settings/import": (api_config.settings_import, ("@ctx", "@data")),
    "/api/cdn/recommendation": (api_cdn.cdn_recommendation, ("@ctx", "@data")),
    "/api/cdn/apply-all": (api_cdn.cdn_apply_all, ("@ctx", "@data")),
    "/api/process-probe/scan": (api_probe.probe_scan, ("@ctx",)),
    "/api/process-probe/start": (api_probe.probe_start, ("@ctx", "@data")),
    "/api/process-probe/stop": (api_probe.probe_stop, ("@ctx",)),
    "/api/process-probe/report": (api_probe.probe_report, ("@ctx",)),
    "/api/games/save": (api_games.games_save, ("@ctx", "@data")),
    "/api/games/check": (api_games.games_check, ("@ctx", "@data")),
    "/api/games/add-domain": (api_games.games_add_domain, ("@ctx", "@data")),
    "/api/games/custom": (api_games.games_custom, ("@ctx", "@data")),
    "/api/frontend-log": (api_probe.probe_debug_log, ("@ctx", "@data")),
}


def init(root_dir: Path, token: str = "") -> None:
    STATE.root_dir = Path(root_dir)
    STATE.app_token = token
    STATE.config_manager = ConfigManager(root_dir)
    STATE.controller = ZapretController(root_dir, config_manager=STATE.config_manager)
    STATE.tester = Zapret2Tester(root_dir)
    api_lists.normalize_user_lists()
    # crash-recovery тест-сессии (logs/test_session_state.json):
    # незавершённый прогон восстановит recovery и защиту (демон-поток)
    session_recovery.start_startup_recovery()


# ── HTTP-хендлер ────────────────────────────────────────────

class ZapretHandler(BaseHTTPRequestHandler):

    # Таймаут сокета: зависший клиент не держит поток вечно (ревью 18.10)
    timeout = 30

    # Глушим штатный лог BaseHTTPRequestHandler
    def log_message(self, fmt, *args):
        pass

    # ── Авторизация ──

    def _host_allowed(self) -> bool:
        """Только loopback-хост: защита от DNS-rebinding (см. do_GET)."""
        host = (self.headers.get("Host") or "").strip().lower()
        if not host:
            return False
        if host.startswith("["):
            name = host.split("]")[0] + "]"
        else:
            name = host.rsplit(":", 1)[0]
        return name in ("127.0.0.1", "localhost", "::1", "[::1]")

    def _check_token(self) -> bool:
        if STATE.app_token:
            token = self.headers.get("x-app-token", "")
            # Header приходит как latin-1 строка. Сравниваем байты: иначе
            # не-ASCII значение даёт TypeError в compare_digest и запрос
            # обрывается без ответа (аудит 24.10).
            try:
                got = token.encode("latin-1", "ignore")
                want = STATE.app_token.encode("ascii", "ignore")
                if not hmac.compare_digest(got, want):
                    self._send_json({"detail": "Forbidden"}, HTTPStatus.FORBIDDEN)
                    return False
            except (UnicodeError, TypeError):
                self._send_json({"detail": "Forbidden"}, HTTPStatus.FORBIDDEN)
                return False
        return True

    # ── JSON-хелперы ──

    def _send_json(self, obj: Any, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str, status: int = HTTPStatus.OK) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path) -> None:
        if not path.is_file():
            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        try:
            body = path.read_bytes()
        except OSError:
            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        ext = path.suffix.lower()
        ctype = CONTENT_TYPES.get(ext, "application/octet-stream")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # no-store: локальный HTTP - дёшево; иначе WebView2 кэширует и правки
        # фронтенда не доходят до пользователя после обновления
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_js_bundle(self) -> None:
        """Склейка frontend/js/app/*.js -> ответ на js/app.js (аудит #2)."""
        try:
            body = _js_bundle_bytes(get_root_dir() / "frontend")
        except OSError:
            self._send_json({"error": "JS bundle incomplete"},
                            HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/javascript; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _parse_body(self) -> Optional[dict]:
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return {}
        if length <= 0:
            return {}
        if length > MAX_BODY_BYTES:
            # Ревью 18.10: без лимита любой мог прислать гигантское тело.
            self._send_json({"detail": "Payload too large"},
                            HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return None
        raw = self.rfile.read(length)
        try:
            obj = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
        if not isinstance(obj, dict):
            self._send_json({"status": "error",
                             "message": "JSON body должен быть объектом"},
                            HTTPStatus.BAD_REQUEST)
            return None
        return obj

    # ── GET ──

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        # Защита от DNS-rebinding: сервер локальный, принимаем только
        # loopback-хост. Иначе сторонний сайт мог бы обратиться к нашему
        # порту «как к своему» и вычитать токен из стартовой страницы.
        if not self._host_allowed():
            self.send_error(403, "Forbidden")
            return

        # Проверка токена для /api/
        if path.startswith("/api/") and not self._check_token():
            return

        try:
            if not self._dispatch(_GET_ROUTES, path, params=params):
                self._handle_static(path)
        except RuntimeError as e:
            self._send_json({"status": "error", "message": str(e)}, HTTPStatus.SERVICE_UNAVAILABLE)
        except Exception as e:
            _probe_debug(f"api 500 GET {path}: {e}")
            self._send_json({"status": "error", "message": str(e)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _dispatch(self, routes: dict, path: str,
                  params: Optional[dict] = None,
                  data: Optional[dict] = None) -> bool:
        """Роутинг по таблице (аудит #1): path -> (цель, спец-аргументы).

        Цель - функция api_*(ctx, ...) нового вида: возвращает dict
        (отправляем как JSON 200) или кидает ApiError(статус, payload).
        "@ctx"/"@params"/"@data" подставляют контекст / query / тело.
        False - маршрут не найден (do_GET: статика, do_POST: 404)."""
        spec = routes.get(path)
        if spec is None:
            return False
        target, args = spec
        vals = [STATE if a == "@ctx" else params if a == "@params"
                else data if a == "@data" else a for a in args]
        if isinstance(target, str):
            getattr(self, target)(*vals)
            return True
        from server.api_common import ApiError
        try:
            result = target(*vals)
        except ApiError as e:
            self._send_json(e.payload, e.status)
            return True
        if result is not None:
            self._send_json(result)
        return True

    def _handle_index(self, params: dict) -> None:
        frontend = get_root_dir() / "frontend"
        index_path = frontend / "index.html"
        if index_path.exists():
            try:
                html = index_path.read_text(encoding="utf-8")
            except OSError:
                self._send_json({"error": "index.html unavailable"},
                                HTTPStatus.NOT_FOUND)
                return
            token = params.get("token", [""])[0]
            # Токен вставляется в JS-строку HTML: принимаем только формат
            # secrets.token_hex(16) (32 hex), иначе отбрасываем -
            # анти-инъекция (ревью 18.10). Сравнение - constant-time в
            # _check_token.
            if len(token) != 32 or any(c not in "0123456789abcdef"
                                       for c in token.lower()):
                token = ""
            else:
                token = token.lower()
                # Не подставляем в страницу произвольный/чужой 32-hex токен:
                # иначе UI получает 403 на каждом /api и выглядит «пустым».
                if STATE.app_token and not hmac.compare_digest(
                        token, STATE.app_token):
                    token = ""
            html = html.replace("__APP_TOKEN__", token)
            # Кэш-buster: версия по mtime app.js / app.css - WebView2
            # кэширует статику, свежие правки не доходили (случай 2026-09-12)
            try:
                js_mtime = int(_js_bundle_mtime(frontend))
                html = html.replace("js/app.js", f"js/app.js?v={js_mtime}")
            except OSError:
                pass
            try:
                css_mtime = int((frontend / "css" / "app.css").stat().st_mtime)
                html = html.replace("css/app.css", f"css/app.css?v={css_mtime}")
            except OSError:
                pass
            self._send_html(html)
        else:
            self._send_html("<html><body><h1>Frontend not found</h1></body></html>")

    def _handle_static(self, path: str) -> None:
        frontend = get_root_dir() / "frontend"
        # /static/... или прямые пути (/css/..., /js/...)
        rel = path.lstrip("/")
        if rel.startswith("static/"):
            rel = rel[7:]
        if rel == "js/app.js":
            self._send_js_bundle()
            return
        file_path = frontend / rel
        # Защита от path traversal (is_relative_to - не строковый
        # префикс: sibling-папка frontend2/backup не проходит)
        try:
            file_path = file_path.resolve()
            frontend_resolved = frontend.resolve()
            if not file_path.is_relative_to(frontend_resolved):
                self._send_json({"error": "Forbidden"}, HTTPStatus.FORBIDDEN)
                return
        except (ValueError, OSError):
            self._send_json({"error": "Forbidden"}, HTTPStatus.FORBIDDEN)
            return
        self._send_file(file_path)

    # ── POST ──

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if not self._host_allowed():
            self.send_error(403, "Forbidden")
            return

        if not self._check_token():
            return

        try:
            data = self._parse_body()
        except (OSError, TimeoutError) as e:
            self._send_json({"status": "error", "message": f"Ошибка чтения тела: {e}"},
                            HTTPStatus.BAD_REQUEST)
            return
        if data is None:
            return
        try:
            if not self._dispatch(_POST_ROUTES, path, data=data):
                self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        except RuntimeError as e:
            self._send_json({"status": "error", "message": str(e)}, HTTPStatus.SERVICE_UNAVAILABLE)
        except Exception as e:
            _probe_debug(f"api 500 POST {path}: {e}")
            self._send_json({"status": "error", "message": str(e)}, HTTPStatus.INTERNAL_SERVER_ERROR)


# ── Жизненный цикл сервера ───────────────────────────────────

class ThreadedHTTPServer(HTTPServer):
    allow_reuse_address = True

    def process_request(self, request, client_address):
        t = threading.Thread(target=self.process_request_thread,
                             args=(request, client_address), daemon=True)
        t.start()

    def process_request_thread(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)


def create_server(host: str, port: int) -> ThreadedHTTPServer:
    srv = ThreadedHTTPServer((host, port), ZapretHandler)
    STATE.server = srv
    return srv


def stop_server() -> None:
    if STATE.server:
        STATE.server.shutdown()
        STATE.server = None
