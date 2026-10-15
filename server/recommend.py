"""recommend.py - финальный вердикт тестера и речек спорных доменов (аудит #1).

Переехало из server.py (Inc C): _build_recommendation / _recommended_blob_keys /
_recheck_contested и их константы. Вызывается из server/tester_flow.py; логика
не менялась.
"""
from __future__ import annotations

import time

from core import timeouts

from core.tester import (CONTROL_DOMAINS, NAKED_BASELINE_HOSTS,
                         QUIC_QUIRK_DOMAINS, RATED_HOSTS, is_control)
from server.app_state import get_config_manager, get_root_dir


# Самые важные для пользователя хосты - показываются в финальном вердикте.
KEY_HOST_LABELS: list[tuple[str, str]] = [
    ("discord.com", "Discord"),
    ("gateway.discord.gg", "Discord (шлюз)"),
    ("www.youtube.com", "YouTube"),
    ("i.ytimg.com", "YouTube CDN"),
]


def build_recommendation(all_results, naked, sanity: dict) -> dict:
    """Финальный вердикт: лучшая стратегия по network_rate, статус ключевых
    хостов (Discord/YouTube), диагноз, если не работает ничего."""
    if not all_results:
        return {"verdict": "no_data", "message": "Нет результатов тестов", "best_profile": ""}

    best = max(all_results, key=lambda r: (r.network_rate, r.net_ok_count))
    # «Не пробито» - провалы ЛУЧШЕЙ стратегии, а не объединение по всем
    # пресетам: домен, который пробила другая стратегия, не должен выглядеть
    # нерабочим (union вводил в заблуждение). QUIC-хосты (youtube-класс) и
    # control-канарейки (google/vk/ya/gosuslugi) вне «не пробито»: их 000 -
    # свойство TCP-пробы сторонним клиентом или мёртвая сеть, не стратегия.
    blocked = sorted({r.domain for r in best.results
                      if r.test_type != "ping" and r.status not in ("OK", "QUIC")
                      and r.domain not in QUIC_QUIRK_DOMAINS
                      and r.domain not in CONTROL_DOMAINS
                      and not is_control(r.domain)})
    net_rate = best.network_rate

    same_as_naked = False
    if naked is not None and naked.results:
        naked_ok = {r.domain for r in naked.results if r.status == "OK"}
        prof_ok = {r.domain for r in best.results
                   if r.test_type != "ping" and r.status == "OK"
                   and r.domain in NAKED_BASELINE_HOSTS}
        same_as_naked = (naked_ok == prof_ok)

    dry = sanity.get("dry_run", {})
    profiles_loaded = dry.get("profiles_loaded")
    engine_broken = (not dry.get("ok", True)
                     or (profiles_loaded is not None and profiles_loaded <= 1))
    misses = [c for c in sanity.get("list_coverage", []) if not c.get("covered")]
    # Пробелы покрытия - НЕ блок: обход работает, но домены вне списков
    # пресета (например, случайные CDN-хосты). Пишем заметкой, не «не пробито».
    miss_note = ""
    if misses:
        doms = ", ".join(c["domain"] for c in misses[:6])
        if len(misses) > 6:
            doms += f" и ещё {len(misses) - 6}"
        miss_note = (f" (не покрыты списками: {doms} - стратегия к ним не применяется, "
                     "доступность может быть нестабильна)")

    # QUIC-хосты (youtube-класс) вне network_rate - ютуб-«прикол» не влияет
    # на вердикт и «не пробито»-чипсы.

    # Равные/почти равные проценты (2026-09-13): при 100/100/100 пользователь
    # не понимает, кого выбирает тестер. Прогон детерминирован (default
    # первым), при полном равенстве побеждает первая протестированная - но
    # это НЕ «эталон»: пресеты равнозначны, для разных сетей лучший бывает
    # разный. ПЛЮС погрешность флаков: 8 хостов - один случайный домен
    # двигает рейтинг на ±12.5%, поэтому стратегии в пределах ±1 домена от
    # лучшей считаются «практически равными» и объясняются так же.
    ranked = sorted(all_results,
                    key=lambda r: (r.network_rate, r.net_ok_count), reverse=True)
    eps_pct = 100.0 / max(best.net_total, 1)
    near_best = [r.profile_name for r in ranked
                 if r.network_rate >= net_rate - eps_pct - 1e-9]
    ties = near_best if len(near_best) > 1 else \
        [r.profile_name for r in all_results
         if abs(r.network_rate - net_rate) < 1e-9]
    tie_note = ""
    if len(ties) > 1:
        tie_note = (f" Практически равный результат (с учётом погрешности "
                    f"прогона ±1 домен) у: {', '.join(ties)} - стратегии "
                    f"равнозначны, рекомендуем {best.profile_name} (первая "
                    "протестированная); если начнёт флакать - переключайтесь "
                    "на другую из списка.")

    # Топ-3 для UI (пользователь видит лучших, а не только рекомендацию)
    top3 = [{"name": r.profile_name, "rate": round(r.network_rate, 1),
             "net_ok": r.net_ok_count, "net_total": r.net_total}
            for r in ranked[:3]]

    if engine_broken:
        verdict = "engine_broken"
        if profiles_loaded is not None and profiles_loaded <= 1:
            message = (f"⚠ winws2 загрузил только {profiles_loaded} профиль(-я) вместо ожидаемых 4-7 - "
                       "сигнатура старого бага с короткими путями (@lua/@blobs). "
                       "Результаты стратегий недостоверны. Обновите программу и повторите тест.")
        else:
            message = ("⚠ winws2 --dry-run отклонил аргументы: "
                       + ("; ".join(dry.get("errors", [])) or "неизвестная ошибка")
                       + ". Результаты стратегий недостоверны.")
    elif same_as_naked and net_rate < 100:
        verdict = "no_bypass"
        message = ("❌ Все стратегии дали тот же результат, что и голый тест (без защиты). "
                   "Обход не применяется: либо winws2 не перехватывает трафик "
                   "(WinDivert/драйвер, антивирус, Killer NIC), либо DPI блокирует любые попытки. "
                   "Запустите «Диагностику» и сохраните отчёт.")
    elif net_rate >= 100:
        verdict = "ok"
        message = f"✅ Лучшая стратегия: {best.profile_name} - {best.net_ok_count}/{best.net_total} доступно.{tie_note}{miss_note}"
    elif net_rate > 0:
        verdict = "partial"
        message = (f"⚠ Лучшая стратегия: {best.profile_name} - {best.net_ok_count}/{best.net_total} "
                   f"({net_rate:.0f}%). Не пробито: {', '.join(blocked) or '-'}{tie_note}{miss_note}")
    else:
        verdict = "no_bypass"
        message = "❌ Ни одна стратегия не пробила блокировку."

    key_hosts = []
    for domain, label in KEY_HOST_LABELS:
        trs = [r for r in best.results if r.test_type != "ping" and r.domain == domain]
        if trs:
            tr = min(trs, key=lambda r: r.time_ms or 0)
            status = tr.status
            note = ""
            # QUIC-класс: TCP-проба сторонним клиентом под десинком не
            # показательная - браузер идёт через QUIC; не красный крест.
            if domain in QUIC_QUIRK_DOMAINS and status not in ("OK",):
                if status == "QUIC" and "подтвержд" in (tr.error or ""):
                    status = "QUIC_OK"
                    note = "H3 подтверждён - в браузере работает через QUIC"
                else:
                    # H3_NONE / нет niquests / TIMEOUT: не клеймим «работает» (внешнее ревью 13.10, P3-1).
                    status = "QUIC_UNKNOWN"
                    note = ("QUIC-проверка недоступна (эвристика)"
                            if "нет niquests" in (tr.error or "")
                            else "H3 не подтверждён - проверьте в браузере")
            key_hosts.append({"domain": domain, "label": label,
                              "status": status, "time_ms": tr.time_ms, "note": note})
        else:
            key_hosts.append({"domain": domain, "label": label,
                              "status": "N/A", "time_ms": 0, "note": ""})

    return {
        "verdict": verdict,
        "message": message,
        "best_profile": best.profile_name,
        "best_network_rate": net_rate,
        "best_ok": best.net_ok_count,
        "best_total": best.net_total,
        "same_as_naked": same_as_naked,
        "blocked_domains": blocked,
        # Домены, чей 000 - свойство QUIC-пробы, а не блок: речек спорных
        # доменов (§29) их не перепроверяет и не помечает «заблокирован».
        # Список берём из tester, а не дублируем строкой: прошлый хардкод
        # разошёлся с ним на storage.googleapis.com (RATED-хост), из-за
        # чего он попадал в «спорные», речекался голым и получал ложное
        # «заблокирован» + до трёх лишних переборов блобов
        # (REVIEW_VERDICT.md §2.2). Единственный источник истины -
        # QUIC_QUIRK_DOMAINS; фронт держит свой QUIRK_HOSTS для таблицы.
        "quirk_skip": sorted(QUIC_QUIRK_DOMAINS),
        "key_hosts": key_hosts,
        "top3": top3,
        "near_best": ties,
        "naked_network_rate": naked.network_rate if naked else None,
        "provider_hop": best.provider_hop,
        "provider_ip": best.provider_ip,
    }


# Ручной приоритет блобов - по живучести на Т2 (STRATEGY_TRIALS батарея
# блобов 2026-09-11, все ниже проверены 6/6 на discord с repeats=7). Ключи =
# имена файлов blobs/tls_clienthello_<key>.bin. www_google_com - эталон
# (пустой fake_blob в конфиге = как в пресете = google). Новые блобы
# добавлять сюда ПОСЛЕ проверки.
BLOB_PRIORITY = [
    "www_google_com",        # эталон, по умолчанию
    "sochi_park",            # проверен в бою 2026-09-10 (отвалы) - стабилен как google
    "mail_ru",               # реальный браузерный hello
    "vk_com",                # реальный, 18 расширений, SNI pos 4 - работает
    "iana_org",              # реальный, 13 расширений
    "hcaptcha_com",          # реальный
    "alfabank_ru",           # реальный
    "www_cloudflare_com",    # синтетика make_blob, реальный домен
    "max_ru",                # большой (664), работал в general
    "web_max_ru",            # мелкий, работал в general
]
# Проверено НЕ пробивающие (Т2): example_com - RFC-заглушка, нереальный
# домен; sni2gis/snimail - тестовые артефакты скрещиваний.
BLOB_STOPLIST = {"example_com", "sni2gis", "snimail"}


def recommended_blob_keys() -> list[str]:
    """Рекомендованные TLS-фейк-блобы: проверенные на Т2 - в РУЧНОМ порядке
    BLOB_PRIORITY (живучесть на Т2, батарея блобов). Фильтры: размер ≤700,
    без _kyber, без имени с цифры (баг winws2, AGENTS правило 2), без
    стоп-листа. Неизвестные блобы - в конец по алфавиту, не рекомендованы."""
    blobs_dir = get_root_dir() / "blobs"
    known: dict[str, int] = {}
    others: list[str] = []
    if blobs_dir.is_dir():
        for f in blobs_dir.glob("tls_clienthello_*.bin"):
            key = f.stem.removeprefix("tls_clienthello_")
            if not key or key.endswith("_kyber") or key[0].isdigit():
                continue
            if key in BLOB_STOPLIST:
                continue
            try:
                if f.stat().st_size > 700:
                    continue
            except OSError:
                continue
            if key in BLOB_PRIORITY:
                known[key] = BLOB_PRIORITY.index(key)
            else:
                others.append(key)
    keys = [k for k in sorted(known, key=known.get)]
    keys += sorted(others)
    return keys


def recheck_contested(tester, best, rec: dict, progress) -> dict:
    """Речек спорных доменов (§29): «заблокирован» vs «временно недоступен».

    В _curl_test пер-хостовых ретраев нет - 000 фиксируется как есть.
    RATED-домен, не пробитый лучшей стратегией, один раз перепроверяется в
    конце прогона: ожившие - «временно недоступен», стабильные 000 -
    «заблокирован». Этап 2 (2026-09-11): перепроверка с альтернативными
    блобами (рекомендованный список, ≤3) - блоб влияет на живучесть у разных
    провайдеров (STRATEGY_TRIALS) - «пробит с блобом X».
    """
    best_failed = {r.domain for r in best.results
                   if r.test_type != "ping" and r.status != "OK"}
    # Домены с известным «приколом» (YouTube TCP/QUIC) не спорны - их 000
    # ожидаем, вердикт уже объясняет QUIC-путь (§17).
    skip = set(rec.get("quirk_skip") or [])
    contested = [d for d in RATED_HOSTS if d in best_failed and d not in skip]
    if not contested or tester.shutdown_event.is_set():
        return rec
    progress(98, "Речек спорных доменов...")
    recheck: dict[str, bool] = {}
    try:
        tester._ensure_winws2_dead()
        for r in tester._run_domain_tests(contested, concurrency=8, expand_www=False):
            recheck[r.domain] = (r.status == "OK")
    except Exception:
        recheck = {}
    if not recheck:
        return rec
    temporary = [d for d in contested if recheck.get(d)]
    confirmed = [d for d in contested if not recheck.get(d)]
    note = []
    if temporary:
        note.append("временно недоступен (ретест): " + ", ".join(temporary))
    if confirmed:
        note.append("заблокирован: " + ", ".join(confirmed))
    rec = dict(rec)
    rec["recheck"] = {"temporary": temporary, "blocked": confirmed}
    # Ожившие на речеке уходят из чипов «не пробито».
    rec["blocked_domains"] = [d for d in (rec.get("blocked_domains") or [])
                              if d not in temporary]
    # ── Этап 2: перепроверка подтверждённо заблокированных с другим блобом ──
    blob_saves: dict[str, str] = {}
    if confirmed and not tester.shutdown_event.is_set():
        progress(99, "Пробуем альтернативные блобы для заблокированных...")
        blob_keys = recommended_blob_keys()
        # текущий блоб пропускаем - он уже не сработал
        cfg = get_config_manager().load()
        current = cfg.fake_blob or ""
        tried = 0
        for key in blob_keys:
            if key == current or tried >= 3 or tester.shutdown_event.is_set():
                continue
            tried += 1
            ok_domains: list[str] = []
            try:
                tester._ensure_winws2_dead()
                if not tester._run_profile(best.profile_name, fake_blob=key) \
                        or not tester._any_winws2_running():
                    continue
                time.sleep(timeouts.SETTLE_BLOB)
                for r in tester._run_domain_tests(confirmed, concurrency=6,
                                                  expand_www=False):
                    if r.status == "OK":
                        ok_domains.append(r.domain)
            except Exception:
                continue
            finally:
                tester._ensure_winws2_dead()
            if ok_domains:
                for d in ok_domains:
                    blob_saves[d] = key
                remaining = [d for d in confirmed if d not in ok_domains]
                if not remaining:
                    break
                confirmed = remaining
    if blob_saves:
        saved = ["%s → блоб «%s»" % (d, k) for d, k in blob_saves.items()]
        note.append("пробит с блобом: " + "; ".join(saved))
        rec["blocked_domains"] = [d for d in (rec.get("blocked_domains") or [])
                                  if d not in blob_saves]
        rec["blob_saves"] = blob_saves
        rec["recheck"]["blocked"] = [d for d in rec["recheck"]["blocked"]
                                     if d not in blob_saves]
    if note:
        rec["message"] = ((rec.get("message") or "").rstrip() + " - " + "; ".join(note))
    return rec
