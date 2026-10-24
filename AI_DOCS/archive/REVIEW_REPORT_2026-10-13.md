# Внешний ревью-отчёт — Zapret 2 GUI (2026-10-13)

> База: `HEAD = 179d00c` (репо `C:\Users\TheFirstNoob\Documents\GitHub\Zapret-2-GUI`).
> Мандат: P0–P1 в свежем контуре (сборка + интеграция QUIC-пробы в тестер);
> остальное — по остатку бюджета.
> Режим: read-only, код не менялся; единственная запись — этот файл.
> Все находки сверены с «закрыто» (`REVIEW_MAP §2`, `REVIEW_VERDICT §1–4`,
> `TESTER_AUDIT`) и «принятыми ограничениями» (`REVIEW_MAP §8`) — переоткрытий нет.
> У каждой находки: репро или строгая цепочка; где нет репро — помечено «гипотеза».

**Итог: P0 — 0 · P1 — 1 · P2 — 4 · P3 — 3.**

---

## P0

Нет.

---

## P1

### P1-1. Exe-сборка молча (exit 0) теряет весь niquests-стек; текущий build-env его не содержит; доки/чеклист не ставят requirements

- **Суть:** commit `87d498b` заявил «bundle niquests[http3] into builds», но сборка
  собирается и БЕЗ установленных зависимостей: `collect_all` для отсутствующего
  пакета не бросает исключение — пишет WARNING в лог и возвращает пустые списки,
  после чего build завершается успешно и выпускает exe без QUIC-пробы.
  На машине автора в build-env (system Python) зависимостей нет.
- **Файлы:** `Zapret2GUI.spec:98-106` (цикл `collect_all` + `except: continue`),
  `requirements.txt:1-3`, `README.md:337-346` (инструкция сборки без
  `pip install -r requirements.txt`), `AI_DOCS/RELEASE_CHECKLIST.md:23-29`
  (то же), `AI_DOCS/AGENTS.md:866-870` (там же открытый пункт
  «проверить сборки на чистой машине»).
- **Цепочка:** нет niquests в env → `collect_all("niquests")` = ([],[],[]) →
  в exe нет ни модулей, ни datas → в рантайме `import niquests` (tester.py:586)
  падает → `_has_niquests=False` → все 5 quirk-хостов уходят в старую эвристику
  `QUIC` при 000, README-состояние «нет niquests» становится постоянным.
  Дополнительно: `except Exception: continue` в spec не срабатывает вообще
  (collect_all не бросает) — пропуск идёт «уровнем ниже», в виде WARNING.
- **Репро (на этой машине, 2026-10-13):**
  ```
  python -c "import sys; print(sys.executable)"
    -> C:\Users\TheFirstNoob\AppData\Local\Programs\Python\Python313\python.exe
  python -m pip list | findstr /I "pyinstaller pywebview urllib3"
    -> pyinstaller 6.21.0 | pywebview 6.2.1 | urllib3 2.7.0   (КЛАССИЧЕСКИЙ)
  python -c "import niquests"      -> ModuleNotFoundError (niquests/qh3/urllib3_future отсутствуют)
  python -c "from PyInstaller.utils.hooks import collect_all; print([len(x) for x in collect_all('totally_missing_xyz')])"
    -> 193 WARNING: collect_data_files - skipping ...  |  195 WARNING: ...  |  result=[0, 0, 0]  (НЕ raises)
  ```
  И это ровно тот python, которым собирается релиз: `build.py:5` (PyInstaller есть
  только здесь), тот же python ставил портативный рантайм (`PY_VER="3.13.14"` =
  версия system python).
- **Минимальный фикс (build-time only):** в spec после цикла проверить
  `_missing = [p for p in (niquests, urllib3_future, qh3) if пакет пустой]` и
  `raise SystemExit("pip install -r requirements.txt …")` без escape-переменной
  окружения (или с ней для осознанных сборок без H3); в README/RELEASE_CHECKLIST
  добавить шаг `pip install -r requirements.txt` перед `python build.py`.
- **Риск регрессии:** низкий; на «правильной» машине поведение не меняется,
  на «неправильной» сборка падает раньше и с понятной причиной.
- **Статус:** **доказано** для «env без niquests» и «тихого пропуска».
  Сам факт работоспособной сборки с niquests — см. H1 (нужна чистая машина).

---

## P2

### P2-1. `_quic_h3_probe` ходит через env/системные прокси (`trust_env=True`) — на машинах с прокси проба мертва (H3_NONE); контракт «niquests env-proxy off» не выполнен

- **Суть:** проба создаёт `niquests.Session(disable_http1=True, disable_http2=True)`
  без отключения `trust_env`; при заданных env-прокси или системном WinINET-прокси
  (urllib `getproxies()` читает реестр) запрос уходит через прокси и падает
  `ProxyError` → `H3_NONE` всегда. Тот же дефект в dev-инструменте.
- **Файлы:** `core/tester.py:599` (Session в `_quic_h3_probe`),
  `tools/quic_probe.py:107`; внешний пруф дефолта — `niquests/sessions.py:438`
  (`self.trust_env: bool = True`). Контракт зафиксирован в `AI_DOCS/AGENTS.md:857-858`
  («niquests env-proxy off»).
- **Репро (h3env, без службы, разрешенная цель i.ytimg.com):**
  ```
  HTTPS_PROXY=http://127.0.0.1:9 ->
    s.merge_environment_settings(...) -> {'proxies': {'https': 'http://127.0.0.1:9', ...}}   # прокси подхвачены
    проба (как в tester.py): box={'err':'ProxyError'}, elapsed=2.09s  ->  (False, "QUIC ProxyError")
    => _curl_test выставит статус H3_NONE с detail "H3 не подтверждён: QUIC ProxyError"
  при s.trust_env=False -> merge_environment_settings -> {'proxies': OrderedDict()}   # чисто
  ```
  `rg -n "trust_env" . -g "!AI_DOCS/**"` — ни одного вхождения в проекте.
- **Минимальный фикс:** после создания сессии — `s.trust_env = False`
  (в `_quic_h3_probe` и в `tools/quic_probe.py`; конструктор `trust_env` не принимает).
- **Риск регрессии:** низкий; на машинах без прокси поведение не меняется.
- **Статус:** **доказано** для «мёртвый прокси» (и in-process merge). Поведение при
  *рабочем* прокси не проверялось — см. H3 (ожидание: тоже провал/деградация, но
  класс риска «ложный успех через прокси» не исключён формально).

### P2-2. Финальная таблица (`statusOf`) красит QUIC/H3_NONE в красный ✗ — прямое противоречие live-отображению и дизайну «серый вместо креста»

- **Суть:** в конце прогона `_fillTable` перезаписывает YouTube-ячейку через
  `statusOf(['www.youtube.com','youtu.be','i.ytimg.com'])`, где «успех» = только
  `OK/OK_BLOCKED`. Все три домена — quirk; их штатные статусы `QUIC`/`H3_NONE`
  дают `✗`. В том же экране вердикт-чип по тому же хосту показывает `✓ QUIC_OK`
  (см. P3-1) — взаимоисключающая индикация.
- **Файлы:** `frontend/js/app.js:3364-3371` (`statusOf`, usage :3370-3371);
  ср. live-путь `frontend/js/app.js:2986-2996` (`hrow-quirk`, «≈ QUIC») и
  `:3008-3012` (ytCell: QUIC → нейтральный бейдж). Дизайн: `frontend/js/app.js:12-14`,
  `AI_DOCS/AGENTS.md:29-34` («статус «≈ QUIC» (серый), не BLOCKED»).
- **Репро (node, логика 1-в-1 из app.js:3364-3369):**
  ```
  statusOf с results=[{...status:'QUIC'}]     -> ERR-marker  (то есть ✗)
  statusOf с results=[{...status:'H3_NONE'}]  -> ERR-marker  (✗)
  ```
  `_fillTable` вызывается по завершении прогона — `frontend/js/app.js:3171, 3273, 3318`.
- **Минимальный фикс:** в `statusOf` добавить ветку нейтрали: есть `QUIC` →
  вернуть серый бейдж «QUIC» (`<span class="st-quirk">QUIC</span>`); все
  `H3_NONE` → нейтральный «–»/warn-точка; иначе как раньше (`OK` → ✓, остальное → ✗).
- **Риск регрессии:** низкий (только отображение; статистика не затронута).
- **Статус:** **доказано** (node-репро + сверка с live-путём; не входит в §8/закрытые).

### P2-3. Live-счётчик «Хосты» (server.`rated`) не учитывает www-алиасы control-хостов → скачок `10/10 → 8/8` в конце прогона

- **Суть:** `_net_stats` (финальный `network_rate`) исключает `www.vk.ru`/`www.ya.ru`
  как алиасы control-хостов (`_is_control_alias`), а серверный `rated`-флаг для
  live-счётчиков этот случай не проверяет (`control`-поле — проверяет!). Итог —
  ровно тот скачок, ради предотвращения которого вводился `rated` (комментарий
  `server.py:467-468`: «чтобы не прыгали (17/17 → 8/8)»).
- **Файлы:** `server/server.py:469-470` (`rated`, алиас не учтён) vs `:471-473`
  (`control`, алиас учтён); `core/tester.py:72-76` (`_is_control_alias`) и
  `:773-776` (`_net_stats`); `frontend/js/app.js:2958, 2972` (live-счёт по rated).
- **Репро (unit, без службы):**
  ```
  python -c "…expand_with_www(TEST_HOSTS)…"
  -> www.vk.ru: server.rated=True  tester._net_stats_excludes=True
  -> www.ya.ru: server.rated=True  tester._net_stats_excludes=True
  -> final net_total=8, live netTotal (правило server.rated)=10
  ```
  (`www.ya.ru`/`www.vk.ru` реально тестируются: `_expand_with_www` даёт www-варианты
  для `ya.ru`/`vk.ru`.)
- **Минимальный фикс:** в `server.py` в условие `rated` (и в `control`) добавить
  `and not _is_control_alias(r.domain)` — импорт `_is_control_alias` из
  `core.tester` рядом с существующим `from core.tester import (RATED_HOSTS, …)`
  (`server.py:20`).
- **Риск регрессии:** низкий (только live-витрина; финальные числа уже верны).
- **Статус:** **доказано** (unit-репро; список-паритет — зона P1-c мандата).

### P2-4. `tls_ver_probe.py`: любой `curl rc=35` трактуется как `UNSUP` — RST/DPI-обрывы рукопожатия маскируются под «стек не поддерживает» и выпадают из suspicion-логики

- **Суть:** `rc == 35` — это и «сервер не умеет такую версию TLS»
  (`schannel … SEC_E_UNSUPPORTED_FUNCTION`), и обычный обрыв handshake
  (`Send failure: Connection was reset` под DPI/RST). Все такие случаи клеймятся
  `UNSUP`, а `all_bad()` не считает UNSUP провалом → предупреждение
  «TLS1.3 валится (возможен DPI по версии TLS)» не срабатывает как раз в целевом
  сценарии.
- **Файлы:** `tools/tls_ver_probe.py:52-54` (классификация), `:60-61` (`all_bad`),
  `:97-102` (выводы).
- **Репро (локальный RST-сервер, ничего внешнего):**
  ```
  сервер 127.0.0.1:44113 с SO_LINGER=0 (accept -> RST), curl --tlsv1.3 --tls-max 1.3:
    rc=35, stderr="curl: (35) Send failure: Connection was reset", stdout="000 0.005"
    tool says UNSUP: True     <— должно быть FAIL (соединение убито)
  контроль: curl --tlsv1 --tls-max 1.0 https://ya.ru/ -> rc=35 "SEC_E_UNSUPPORTED_FUNCTION"
            (вот это — законный UNSUP)
  ```
- **Минимальный фикс:** при `rc==35` требовать «unsupported»-специфику в stderr
  (`SEC_E_UNSUPPORTED_FUNCTION`, `SEC_E_ALGORITHM_MISMATCH`, `not supported`,
  `unsupported`); иначе — `FAIL`.
- **Риск регрессии:** низкий (dev-инструмент).
- **Статус:** **доказано** (локальный репро).

---

## P3

### P3-1. Вердикт-чип называет `QUIC_OK` любой non-OK статус quirk-хоста — включая `H3_NONE` (и даже TIMEOUT/BLOCKED), с текстом «в браузере работает через QUIC»

- **Суть:** `server.py:906-908` заменяет любой статус != OK на `QUIC_OK` + ноту
  «TCP-проверка неприменима — в браузере работает через QUIC». UI считает это
  зелёным «доступен» (`app.js:3492-3499`). В сборке без niquests (P1-1) это
  превращается в безусловное «YouTube доступен». Плюс нюанс: `time_ms` для
  QUIC-результата — время провального TCP-этапа (~6с), т.к. `elapsed` в
  `tester.py:545/556` замеряется ДО H3-пробы, а чип показывает именно его.
- **Файлы:** `server/server.py:897-913`; `frontend/js/app.js:3492-3499`;
  `core/tester.py:544-566`.
- **Цепочка:** H3-проба не подтвердила (деталь в `error`) → статус H3_NONE →
  `_build_recommendation` → `QUIC_OK` → зелёный чип «✓ … QUIC / доступен».
- **Минимальный фикс:** различать «H3 подтверждён» (OK-чип) и «не подтверждён»
  (нейтральный чип с нотой «проверьте в браузере»); при желании — показывать
  время H3-пробы, а не TCP-этапа.
- **Статус:** **доказано** по коду (цепочка + node-логика UI); влияние — UX.

### P3-2. `quic_probe.py`: сообщение DoH-фолбэка «повтори запуск» бесполезно без `--repeat`

- **Суть:** `install_doh_patch` ставит monkey-patch в текущем процессе и пишет
  «повтори запуск»; при перезапуске процесса патч теряется, у `--repeat>1` —
  работает уже в следующем круге. Сообщение вводит в заблуждение.
- **Файлы:** `tools/quic_probe.py:77-90, 138-144`.
- **Минимальный фикс:** текст «патч активен в этом процессе; используйте
  `--repeat 2`» либо ставить патч сразу на повтор внутри процесса.
- **Статус:** **доказано** по коду (простая цепочка; влияние — dev-tool UX).

### P3-3. `upload_probe.py`: сводка ladder противоречива для немонотонных прогонов

- **Суть:** при `bad=[512,…]`, `ok=[65536]` печатается «OK до 65536Б, ломается на
  512Б» — взаимоисключающие слова для немонотонного результата (флап).
- **Файл:** `tools/upload_probe.py:124-133`.
- **Фикс:** формулировать как «пороги неоднородны: ломается на …; OK на …».
- **Статус:** по коду, косметика (влияние минимальное).

---

## Проверено — НЕ находки (не перепроверять)

- **`_has_niquests` при параллельных вызовах** (`tester.py:584-590`, пул 8):
  гонка безвредна — per-module import lock + атомарная запись атрибута класса;
  худшее — повторный `import` (no-op). Не баг.
- **`box`-dict / daemon-хвост H3-пробы:** принятое ограничение §8, подтверждаю:
  чтения `box` происходят только после `join` при `is_alive()==False`;
  зависший поток ограничен внутренними (4,8).
- **Бюджет времени с H3-пробой:** худший случай ~18–19с на квирк-хост
  (HEAD 3с + GET 3с + H3-wall 12с), 5 хостов параллельно (пул 8) — итог
  фазы curl ≤ ~20с/профиль. Приемлемо, ограничение заявлено заранее.
- **DNS-спуф → `H3_NONE`, отсутствие DoH в тестере** — известный backlog
  `AGENTS.md:818-820` (приоритет №1 0.11), не находка.
- **Статусы в `test_logger.py` / `_serialize_result` / экспорт-отчёте:** логики
  по статусам нет — поломки не существует; `H3_NONE`/`QUIC` в них нейтральны.
- **`_build_result` ok/fail vs `_net_stats`:** H3_NONE/QUIC только на quirk-хостах,
  которые исключены из net — протечки в fail/OK нет; списки fail-статусов в
  `_build_result`/`_build_recommendation`/`_recheck_contested` согласованы.
- **Сборка стека статически (симуляция реального `collect_all` из PyInstaller
  6.21 против h3env):** niquests 54 hidden / urllib3_future 124 / urllib3(зеркало)
  124+130 datas / qh3 22 hidden / wassima 8 / jh2 24 / h11 11 — ключевые имена на
  месте (`urllib3.contrib.webextensions.sse`, `urllib3.contrib.socks`,
  `qh3._hazmat`, `niquests.packages`, `niquests.adapters`); зеркало `urllib3/`
  полное (diff с `urllib3_future/`: 0 отсутствующих файлов); `qh3._hazmat` —
  обычная статическая ветка импорта (`qh3/connection.py:12`), т.е. `.pyd` попадёт
  в бандл и без `collect_all`-binaries (collect_all вернул binaries=0 — это норма).
- **`cryptography` в `EXCLUDES`:** в niquests/wassima/urllib3_future нет ни одного
  импорта cryptography (grep) — исключение безопасно для QUIC-пробы.
- **`h11` вне EXCLUDES:** импортируется только `niquests/help.py` (в рантайме
  нигде не импортируется) — лишний вес незначителен, конфликтов нет.
- **wassima:** при пустом OS-сторе есть embedded-CCADB фолбэк
  (`wassima/__init__.py:131-132`); исключение из `_root_der_certificates()` не
  перехвачено — см. H4.
- **Python-embed 3.13.14:** URL живой (HTTP 200, 10 964 839 Б == размер
  закешированного `build/python-embed.zip`); qh3-wheel `cp37-abi3-win_amd64`
  (maturin) — совместим с 3.13 embeddable.
- **`build_portable` порядок манифеста** (`:143-152`) — сначала чистка `__pycache__`,
  затем `write_manifest`; `write_manifest` сам отсекает `__pycache__/.pyc`
  (`updater.py:562`). Верно.
- **Updater (беглый проход):** траверсал-проверки (`updater.py:374-377`), сверка
  sha по манифесту (`:388-390`), fail-closed exe-замена (`:425-438`) — на месте.
  Глубокая ревизия `tools/release_publish.py`/`tools/security/*` не проводилась
  (вне бюджета этого прохода).
- **Синтаксис:** `py_compile` по `core/tester.py, build.py, build_portable.py,
  tools/quic_probe.py, tools/upload_probe.py, tools/tls_ver_probe.py,
  server/server.py, core/updater.py, core/config.py`, `Zapret2GUI.spec`,
  `node --check frontend/js/app.js` — все зелёные.

---

## Гипотезы, требующие чистой машины / полной сборки

- **H1. Прогон exe-сборки с niquests на провижн-машине.** Что проверить:
  `pip install -r requirements.txt` в build-env → `python build.py` → запустить
  `dist\Zapret2GUI.exe` → на квирк-хосте в колонке error должно быть
  «H3 подтверждён …» (или ошибка H3, но НЕ «нет niquests»). Статически цепочка
  разобрана и выглядит целой (см. «не находки»), но рантайм-резолв
  alias-импортера `niquests.packages.urllib3.*` в frozen-PYZ проверяется только
  живой сборкой.
- **H2. Portable-сборка с niquests на чистой машине.** В `build_portable.py` pip
  ставит `niquests[http3]` (строка 112-113) в embeddable-python; зеркало
  `urllib3/` создаётся `urllib3_future.pth` при запуске python на этапе сборки и
  попадает в zip уже готовым (проверить, что после сборки в
  `portable/python/Lib/site-packages/urllib3/` лежит полная копия и в
  установленном на чистой машине portable проба работает без прав записи).
- **H3. env-прокси + рабочий прокси.** Проверен только мёртвый прокси (P2-1).
  Для рабочего прокси остаётся вопрос: «деградация в H3_NONE» или (маловероятно)
  «ложное подтверждение H3 через прокси» — решается после фикса `trust_env=False`
  или экспериментом с локальным прокси.
- **H4. wassima без доступного ROOT-стора.** Пустой стор покрыт embedded-фолбэком;
  исключение при чтении стора (не пустой ответ, а raise) не перехвачено ни в
  wassima, ни в niquests (`_constant.py:18-24`) — на Windows маловероятно, но
  чистого репро «стор недоступен» нет.

---

## Артефакты (что именно смотрелось)

- Код: `core/tester.py` (целиком по зонам), `server/server.py` 420-520, 780-959,
  993-1069, 2721-2772; `frontend/js/app.js` 1-40, 2930-3050, 3345-3384, 3470-3514;
  `core/test_logger.py`, `core/collector.py` 130-209, `core/updater.py` 330-403,
  540-568; `core/config.py`; `build.py`, `build_portable.py`, `Zapret2GUI.spec`,
  `build_lite.py` (бегло), `requirements.txt`;
  `tools/quic_probe.py`, `tools/upload_probe.py`, `tools/tls_ver_probe.py`.
- Внешние пакеты (h3env): `niquests/_compat.py`, `packages.py`, `sessions.py`,
  `_constant.py`, `extensions/*`; `wassima/__init__.py`; `qh3` структура;
  `urllib3_future` зеркало/.pth; `niquests-3.21.2.dist-info/METADATA`.
- Доки: `REVIEW_MAP.md`, `REVIEW_VERDICT.md`, `TESTER_AUDIT.md`,
  `RELEASE_CHECKLIST.md`, `AGENTS.md` (снапшот/бэклог/QUIC-блок), README FAQ.
- Репро-скрипты выполнялись из read-only позиции (unit-вызовы, локальный сервер,
  node-симуляция логики); полный прогон тестера, сборки и служба не трогались.
