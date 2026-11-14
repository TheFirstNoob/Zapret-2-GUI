# Готовность Pre-Release 0.11 к публикации (2026-11-14)

> HEAD: `42edee7` + незакоммиченные README/CHANGELOG/фикс security-теста.
> Цель: зафиксировать вердикт и точную последовательность перед тегом.
> Проверяли: T25 README, T26 батарея/гейты, T27 updater/release,
> T28 service-код-фриз, T29 tester-код-фриз (отчёты —
> `_analysis/release-0.11/`, локально, gitignored).

## Вердикт: НЕ ГОТОВ к публикации

Механика релиза и код-батарея готовы, но нет 0.11-артефактов/подписи,
не пройдена live-приёмка и не закоммичен код-фриз. Публиковать сейчас —
нельзя: `release_publish --version 0.11 --dry-run` возвращает отказ.

## Блокеры

1. **B1. Нет 0.11-артефактов.** `Windows build/*.zip` и `release.json` в репо —
   от 0.10 (внутри VERSION 0.10, движок 1.0.5). Черновики 27.10 на Desktop —
   1.0.6 и без runtime-секции, подписывать их нельзя. Нужна пересборка трёх
   архивов из HEAD (1.0.7 + `midsld` + runtime manifest).
2. **B2. Нет подписи 0.11.** `release.json.sig` — 0.10; офлайн-ключ
   (PUBKEY `50DCECF29451`) не применялся. Подписывать только свежие архивы.
3. **B3. Артефакты и манифест должны быть закоммичены ДО тега.**
   `release_publish` создаёт тег от текущего `main`, но не проверяет, что
   `Windows build/*`, release.json и .sig закоммичены; иначе тег и jsDelivr
   `@tag` будут без артефактов.
4. **B4. jsDelivr-лимит 20 MB/файл.** У 0.10 exe-zip 21.43 MB, portable
   20.17 MB — канонический exe-zip, вероятно, не отдаётся зеркалом
   (`updates.MIRROR_URL` всегда ведёт на exe-zip). После сборки измерить
   размеры; если >20 MB — запросить лимит/ограничить зеркало честно.
5. **B5. Live-приёмка не пройдена:** реальные install/remove/repair/restart
   службы и failure actions; crash-recovery журнала службы; portable-апдейт
   (в т.ч. 0.10→0.11 reinstall); exe-апдейт при работающем обходе; тестер/H3/CDN
   на реальной сети; DNS apply/reset; Win10/PS5.1, две копии GUI.
6. **B6. Код-фриз:** README/CHANGELOG/security-тест/docs не закоммичены;
   после коммита перегнать батарею и больше не менять код до тега.

## Зелёное (проверено 2026-11-14)

- `compileall` OK; `pytest tests` **317 passed**; security **47 passed**
  (прямой runner теперь тоже 47); `api_smoke` OK; `args_golden` OK;
  `check_arg_file` OK (11/11); `js_bundle` OK; `status_contract` OK.
- Гейты работают: `release_publish --dry-run 0.11` падает с точными ошибками
  (version/tag 0.10, нет `runtime.rev`); `sign_release` откажет на старых
  архивах (inner 0.10 / engine 1.0.5 ≠ 1.0.7); `check_for_updates()` показывает
  опубликованную 0.10, а не draft 0.11 (ложный баннер устранён).
- Portable runtime-апдейт (python.new → switch bat → rollback → post-check)
  и exe-апдейт при живой службе реализованы и покрыты тестами.
- README реструктурирован (TOC/якоря проверены), CHANGELOG 0.11 дополнен и
  соответствует текущему коду; фактические ошибки README исправлены.
- `hosts.txt`, release-гейты, pretty-имена ассетов, WebView2 fallback,
  DNS-профили, H3-пробы — проверены статически/тестами.

## Обязательная последовательность перед тегом

1. Закоммитить README/CHANGELOG/security-тест/docs (код-фриз), `git status` чист.
2. Пересобрать из HEAD: `python build.py`, `python build_portable.py`,
   `python build_lite.py`; проверить внутри архивов VERSION 0.11, движок 1.0.7
   и runtime-секцию portable.
3. Повторить батарею (317/47 + tools) и `check_arg_file` на чистом дереве.
4. `sign_release.py --version 0.11 --tag Pre-Release-0.11 --key <offline>`;
   отпечаток = `50DCECF29451`; самопроверка подписи зелёная.
5. `release_publish.py --dry-run` должен быть ОК (VERSION/tag/manifest/
   подпись/sha256/size/runtime); иначе не публиковать.
6. Закоммитить `Windows build` zip+sha256, `release.json`, `release.json.sig`;
   перепроверить `git status` и dry-run уже после коммита.
7. Измерить размеры ассетов (<20 MB для jsDelivr) и решить по B4.
8. Опубликовать (`--keep-draft` → проверить 8 ассетов → publish).
9. Смоук: обновление 0.10 portable → 0.11 (reinstall), 0.11→0.11 runtime,
   проверка подписи/хешей и jsDelivr-доступности.
10. Пройти live-чек-лист §B5; результаты — в release notes / отчёт.

## Остаточные риски (не блокеры кода)

- **Service (T28):** R1 fail-closed precheck на restore-путях может оставить
  службу остановленной при инфраструктурном сбое; R2 три P1-фикса `a64d25a`
  без unit-тестов (live-only); R3 recovery читает журнал до `_op_lock`;
  R4 remove в stuck-delete может блокироваться ~20–25 c; R5 orphaned takeover
  не убивает winws2 из мёртвого stored-пути.
- **Tester (T29):** P3 F1 cancel_event не прокинут в H3; F4/F5 мёртвый дрейф
  таймаутов; F7 custom строится после отмены; F8 api_cdn не видит
  list-exclude-user. P2: CDN-скан на очень медленном линке может удлиниться.
- **Tooling (T26):** нет unit-тестов на release-гейты; api_smoke не герметичен
  при stale crash-журнале; CI хардкодит v1.0.7; exe-архив не гейтится по VERSION.
- **Лицензия:** V3nilla/RIPEstat — решение владельца; ipset staged ждёт A/B.

## Live-чек-лист (минимум до «всё исправлено» в нотах)

1. install → start → stop → restart → repair службы; failure actions.
2. Kill GUI посреди операции службы → журнал/восстановление при старте.
3. Переименовать папку → orphaned/takeover; удалить службу из живой копии.
4. Portable 0.10 → 0.11 (reinstall) и 0.11 → 0.11 runtime-апдейт.
5. Exe-самообновление при работающем обходе (данные не ломаются).
6. Тестер/H3/CDN на реальной сети; отмена во всех действиях.
7. DNS apply/reset на Wi-Fi/Ethernet/VPN (IPv6, 3+ сервера).
8. Win10 без WebView2 Runtime; PS5.1; путь с пробелом/кириллицей; две копии GUI.

## Отчёты

`_analysis/release-0.11/README-review.md`, `release-audit-tooling.md`,
`release-audit-updater.md`, `release-audit-service.md`,
`release-audit-tester.md` (локально, gitignored).
