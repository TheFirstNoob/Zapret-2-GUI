# Upstream sync 2026-11-14 — dpi-detector / dpi-checkers / Flowseal

> Пользовательские ссылки: `Runnin4ik/dpi-detector`, `hyperion-cs/dpi-checkers`,
> коммит Flowseal `2401b7a` («Обновить IPSet»). Задача: обновить то, что нужно,
> посмотреть списки/ASN Checker. Подробные отчёты с диффами/хэшами и PoC —
> локально в gitignored `_analysis/upstream-sync/` (544/548/548 строк).

## 0. Итог одной таблицей

| Что | Решение |
|---|---|
| Данные dpi-detector (`tcp16.json`, `whitelist_sni.txt`) | **не обновлять**: наш снимок байт-в-байт = upstream main/jsDelivr/rust (diff 0/0/0). Бандлим как есть |
| Данные dpi-checkers (`suite.v2.json` → `CDN_HOSTS`) | **не обновлять**: 36/36 хостов, порядок 1:1; upstream не менялся с 2026-06-16. Статических IP/CIDR у них нет |
| Flowseal `2401b7a` (IPSet) | это **копия V3nilla** `ipset-all.txt` (коммит 1fe2025, 33336 строк); нового источника нет. Наша база **не менялась**; staged-база готова для A/B |
| ASN Checker | **исправлены P0/P1**: HTTP-пробы (порт 80), per-item SNI (7 Fastly), OK по полной отправке 32 КБ, порог DETECTED 12 КБ; SNI проброса в API/UI |
| Лицензии | добавлена атрибуция dpi-detector (MIT © Runnin4ik) и dpi-checkers (Apache-2.0); по V3nilla/RIPEstat — см. §4 (решение владельца) |
| Списки доменов Flowseal | не трогаем: другая архитектура, `^-синтаксис`, пересечение незначимо; hosts/blobs — без A/B не берём |

## 1. dpi-detector (Runnin4ik)

- Stable **v4.2.4** (2026-09-04), `main` заморожен (`8d6d25a`); активность
  2026-11-09 — prerelease-ветка `rust` (v5.0.0-alpha.21, Rust-переписка), данные
  там те же; **v5 не берём** (alpha, нет stable).
- `lists/cdn-asn-probes.json` = `tcp16.json` (11241 B, sha256
  `546c14d6d3fd120884111bbc37da4a3367ee98f42716d58c6bb6d932a2dc7b12`),
  `lists/whitelist-sni.txt` = `whitelist_sni.txt` (3265 B, sha256
  `0f85b93e7a15c8d5f53aa1abb02f81eade6d5645217f6cf155dbecbea73ffa41`).
  Хэши закреплены тестом `tests/test_dpi_detector_data.py`; обновление —
  `python tools/sync_dpi_detector.py [--apply]` (jsDelivr → raw, cross-check).
- `domains.txt` upstream **не бандлим** (рантаймом не читается; тест 4 «sweep SNI» — P2).
- Исправленная семантика ASN-скана (`core/tester.py`, T16): порт из пробы
  (6/110 HTTP), per-item `sni` (7 Fastly FST-01..07), OK = полная отправка
  32 КБ (не по HTTP-коду), DETECTED только при обрыве ≥12 КБ (<12 КБ = TIMEOUT),
  опциональный SNI в API/UI. Baseline 104/110 снят до правок — живой прогон на
  RU-сети после мерджа не выполнялся.
- Лицензия MIT © 2026 Runnin4ik — добавлено в `THIRD_PARTY_NOTICES.md`.

## 2. dpi-checkers (hyperion-cs)

- `CDN_HOSTS`/`CDN_PROVIDERS` (`core/tester_defs.py`) = `ru/tcp-16-20/suite.v2.json`
  36/36, порядок сохранён (sha256 `9c844313a8120e54…f50e7e`, 2026-06-16);
  проверено против HEAD `bb38d7a` (2026-09-23) — без изменений.
- Производные: `lists/list-cdn-test.txt` (12), `lists/list-cdn-fix.txt` (9),
  8 fix-хостов в `lists/list-general.txt`.
- Лицензия Apache-2.0; атрибуция добавлена (THIRD_PARTY_NOTICES, README,
  ENGINEERING_NOTES §1, комментарий у `CDN_HOSTS`).
- **Не делаем:** бандл `dpich` (6–7 МБ Go/TUI/самоапдейт), RU whitelist-CIDR
  флот (38 ASN/3469 префиксов, пересечение с нашим ipset 3/3469), DWC-список
  266 доменов (2025-07-02, ∩ whitelist-sni 4/266), GeoLite2/dynamic farming
  (EULA/лицензия, не наш кейс).
- **Post-0.11 backlog (полезные идеи, данных чужих не требуют):**
  1. **P1:** 3-й рунг SNI-swap в `core/diagnostics.py::classify_block` —
     real → benign(google/cf) → whitelist-SNI (`vk.ru/ya.ru/gosuslugi.ru`),
     новый kind `sni_whitelist` (~18 строк). Прямо про GGC/YouTube-класс
     «проходит только whitelist-SNI».
  2. **P2:** precheck «режим CIDR-whitelist» в ASN-скане: 3 whitelisted
     (max.ru/ya.ru/vk.ru) vs 3 обычных (github/wikipedia/google) — иначе
     массовый SYN DROP трактуется как «IP протухли» (~45 строк).
  3. **P3:** tcp16-20 «метод 2» (HEAD с URI ~7 КБ ×9) — наш метод 1 (POST 64 КБ)
     покрывает типовой кейс, добавляет статус/шум контракта.

## 3. Flowseal / ipset

- Коммит `2401b7a` (2026-11-04, PR #18572, автор V3nilla) — байт-в-байт копия
  V3nilla `ipset-all.txt` (коммит `1fe2025`, sha256 `63823a20…`, 33336 строк =
  26485 v4 + 6851 v6); Flowseal лишь нормализует LF в `.service/ipset-service.txt`.
  Своего генератора у Flowseal нет (генератор — V3nilla `AS_Parser.py`,
  stat.ripe.net, 98 ASN; с 27.08 не менялся ⇒ только BGP-churn).
- Наша база (`26441 CIDR`, v4-only) **не менялась** в 0.11.
- Coverage-diff 2026-11-14: upstream-not-covered нами = **1123 CIDR /
  1 119 764 адр.**; наше-not-covered ими = 1287 CIDR / 1 330 545 адр.
  (терять нельзя: upstream удалил ~964 тыс. адр., в т.ч. агрегат CF
  `104.16.0.0/12` и Amazon EU Sovereign `51.72/15+51.224/15`; у нас они есть).
- Staged-база: `27206 CIDR` (89 394 B, sha256 `9d9733de…`) —
  `python tools/ipset_stage_merge.py --candidates ... --out <local>`. Релизную
  базу меняет только `--apply-base`.
- **A/B обязателен до применения** (catchall, CDN-сканер 36 хостов, WARP off,
  служба stop/restore) + ручной break-class чек: Fastly `90.98.0.0/18`,
  CF `69.195.160.0/19`, Oracle/AWS/NTT/Level3. Слабые свидетельства сейчас:
  0/110 ASN-проб в добавках; DNS-резолв 21 CDN-домена — 0 попаданий (A/B не заменяет).
- **v6 не вливать** (6851 подсеть): поддержку `--ipset` v6 в winws2 1.0.7 сначала
  проверить на стенде.
- Восстановлены инструменты: `tools/ipset_diff_v3nilla.py`,
  `tools/ipset_candidates.py`, `tools/ipset_stage_merge.py`; правила —
  `AI_DOCS/IPSETS_V3NILLA.md` (восстановлен из git-истории, обновлён замером).

## 4. Лицензии и решение владельца

- **V3nilla** — в репо нет LICENSE; данные — производные **RIPEstat Data**.
  RIPEstat ToC §3.3 ограничивает re-packaging/redistribution (коммерческое —
  только с письменного разрешения RIPE NCC); §3.2 — атрибуция. Наша база —
  производное от этих данных. Добавлена пометка в `THIRD_PARTY_NOTICES.md`;
  **решение владельца**: оставить как локальный диагностический список /
  запросить разрешение RIPE NCC / заменить источник перед коммерческим релизом.
- Flowseal — MIT (`LICENSE.txt` sha256 `fe3983a1…`), dpi-checkers — Apache-2.0
  (NOTICE нет), dpi-detector — MIT © Runnin4ik.

## 5. Где сырьё

`_analysis/upstream-sync/00-BRIEF.md`, `01-dpi-detector.md` (544 стр.),
`02-dpi-checkers.md` (548 стр.), `03-flowseal-ipset-lists.md` (37.8 KB),
`scratch-t16/`, `scratch-t17/`, `scratch-lead/` (staged gz + diff/compare PoC).
В репозиторий не коммитится (gitignored), в docs — только обезличенная выжимка.
## 6. Как читать снимок hyperion TCP16-20 (пример: T2 моб., без WARP)

Пользовательский снимок: `Alive=Yes` у большинства узлов, `TCP 16-20 =
Detected` у SE.AKM-01, DE.DO-01, UK.DO-02, US.FTBVM-01/02, US.GC-01/02,
FR.OVH-01; `No 🔴 / Skip` — у CDN77-01, Contabo FR, Hetzner DE, Vultr,
OVH-02, Oracle SG; `Unknown/Unlikely` — FI.HE-02, US.MBCOM-01.

- Это **stateful-DPI по направлению upload**: TLS-handshake проходит (Alive
  Yes), POST 64 КБ обрывается в окне 16–20 КБ. Класс не SNI-специфичный:
  набор «Detected» — ровно break-class хостинги (DO/OVH/BuyVM/GC/Akamai),
  которые нельзя включать в широкий ipset (наш A/B 2026-10-10).
- `No/Skip` = Alive-проверка (HEAD/TLS) не прошла; это не отдельный класс
  блокировки: узел может быть недоступен/гео-фильтр/rate-limit/чужой vhost.
- `Unknown/Unlikely` — таймауты/неопределённость чекера, не «блок».
- Наш ASN-скан (`asn_scan`) и CDN-батарея измеряют то же самое, но иначе:
  ASN-скан — 110 IP с белым SNI и без нашего обхода; CDN-батарея — домены
  **под** обходом (fix/break). Их нельзя сравнивать построчно с hyperion:
  разные IP, SNI и направление/метод.

### Механизмы, которые можно добавить (приоритеты)

1. **P1 — SNI-swap второй проход** для DETECTED-проб: повторить с benign
   (`example.com`/google) и whitelist-SNI (`vk.ru/ya.ru/gosuslugi.ru`),
   получить класс `ip` (всё DETECTED) / `sni` (real DETECTED, benign OK) /
   `whitelist` (только whitelist OK). Прямо про GGC/YouTube-класс, ~40 строк.
2. **P1 — UI-сводка профиля DPI**: агрегаты по классам/провайдерам +
   предупреждение «break-class → ipset catchall не включать» + рекомендации
   (домен в «Спорные домены», пробовать fake-disorder/fakedsplit/QUIC).
3. **P2 — метод 2 TCP16-20** (HEAD с URI ~7 КБ ×9): отличать «сервер режет
   upload» от stateful DPI; снижает ложные DETECTED (413/лимит загрузки).
4. **P2 — whitelist-mode precheck** (3 whitelisted vs 3 обычных URL):
   при массовом SYN DROP отличать «IP протухли» от CIDR-whitelist режима.
5. **P2 — повторы/медиана** для DETECTED/TIMEOUT и статус UNKNOWN вместо
   ложного OK/ERROR на мобильных рывках.
6. **P3 — 64 КБ «тщательный» режим** с точной точкой обрыва (32 КБ хватает
   для 16–20, но не отделяет обрыв >20 КБ; на мобиле трафик ×2).

### Что делать со списками

- **Не добавлять** обнаруженные provider-CIDR в `ipset-all` (break-class;
  ipset catchall их ломает) и не менять `CDN_HOSTS`/`whitelist-sni` —
  они и так актуальны/идентичны upstream.
- **Можно добавить** `lists/list-whitelist-sni.txt` (max.ru, ya.ru, vk.ru,
  gosuslugi.ru) как контрольные домены для будущего SNI-swap/precheck
  (наш curated список, лицензионно чисто).
- **Код-карта break-class ASN** (DO 14061, Hetzner 24940, OVH 16276,
  Vultr 20473, FranTech/BuyVM 53667, GC 396982, …) — для предупреждений в UI,
  чтобы никто не «лечил» эти детекты широким ipset.
- **Не брать**: DWC-266, RU whitelist-CIDR флот, dpich, GeoLite2 (см. §2).
- Доменные списки Flowseal/`list-cdn-test` по этому снимку не меняются: он
  про hosting-IP, а не про домены.
