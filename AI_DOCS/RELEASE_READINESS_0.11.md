# Pre-Release 0.11 — опубликован, live-приёмка остаётся

> Обновлено 2026-11-14. Сборка: `64f9fd1`, релиз: `f29cdb3`, тег
> `Pre-Release-0.11`. Отчёты аудита: `_analysis/release-0.11/` (локально,
> gitignored).

## Вердикт: опубликован 2026-11-14; live-приёмка остаётся

Релиз: https://github.com/TheFirstNoob/Zapret-2-GUI/releases/tag/Pre-Release-0.11

Тег `Pre-Release-0.11` → `f29cdb3`, 8 pretty-ассетов загружены и проверены
по sha256/размерам; `release.json`/`.sig` подписаны (`50DCECF29451`).
`check_for_updates()` видит latest 0.11. Осталось пройти live-смоук и не
обещать «всё исправлено» до него.

## Что уже сделано

| Шаг | Результат |
|---|---|
| Сборка EXE | `Zapret2GUI.zip` 21 513 599 B, sha256 `dae51087…`; exe 0.11.0.0, движок 1.0.7 |
| Сборка portable | `Zapret2GUI-portable.zip` 18 616 620 B, sha256 `459529f1…`; runtime.rev `070a007233a8483c` |
| Сборка lite | `Zapret2GUI-lite.zip` 1 795 494 B, sha256 `6bd659e7…`; VERSION 0.11, движок 1.0.7 |
| Подпись | `release.json` + `release.json.sig` созданы; отпечаток `50DCECF29451` |
| Publish dry-run | **RC=0**, 8 pretty-ассетов; VERSION/tag/manifest/runtime/sha256/size сходятся |
| Батарея после сборки | 317 tests, 47 security (direct runner 47), compileall/api_smoke/args_golden/check_arg_file/js_bundle/status_contract — OK |
| Артефакты внутри | portable: 834 файла, runtime-секция; lite: 126 файлов; flaky/runtime-файлов нет; движок 1.0.7 |

## Остающиеся шаги

Релиз опубликован. Осталась только live-приёмка: portable 0.10→0.11
(reinstall), 0.11→0.11 runtime, install/remove/repair службы, exe-апдейт при
живой службе, тестер/H3/CDN, DNS на адаптерах, Win10/PS5.1. До неё не
писать в нотах «всё исправлено».

## Известное ограничение: jsDelivr >20 MB

- portable 17.8 MiB и lite 1.7 MiB зеркалом отдаются; полный exe-архив
  20.5 MiB (21 513 599 B) превышает лимит jsDelivr 20 MB.
- Совместимый deflate-level9 не помогает (20.51 MiB); LZMA ≈20.0 MiB и
  несовместим с Explorer/старыми клиентами — не используем.
- Решение 0.11: GitHub — основной источник; portable/lite — зеркало.
  В README/CHANGELOG это записано. Пост-0.11: решить лимит/отдельный
  источник для full exe, не менять формат поздно.

## Код-фриз и остаточные риски

- Service (T28): P0 нет; live-only R1–R5 (fail-closed precheck, журнал до
  `_op_lock`, stuck-delete, orphaned takeover); три фикса `a64d25a` без unit-тестов.
- Tester (T29): P0/P1-регрессий нет; P3 F1/F4/F5/F7/F8, P2 медленный CDN-скан.
- Tooling (T26): release-гейты и security-раннер (47) OK; нет unit-тестов на
  `release_publish`; api_smoke не герметичен при stale crash-журнале.
- Docs: README реструктурирован и выправлен (P0 факты), CHANGELOG 0.11
  актуален, RELEASE_CHECKLIST/B4-шаги обновлены.

## Live-чек-лист (обязателен до «всё исправлено» в нотах)

1. install → start → stop → restart → repair службы; failure actions.
2. Kill GUI посреди операции службы → журнал/восстановление при старте.
3. Переименовать папку → orphaned/takeover; удалить службу из живой копии.
4. Portable 0.10 → 0.11 (reinstall) и 0.11 → 0.11 runtime-апдейт.
5. Exe-самообновление при работающем обходе.
6. Тестер/H3/CDN на реальной сети; отмена во всех действиях.
7. DNS apply/reset на Wi-Fi/Ethernet/VPN (IPv6, 3+ сервера).
8. Win10 без WebView2; PS5.1; путь с пробелом/кириллицей; две копии GUI.

## Отчёты

`_analysis/release-0.11/README-review.md`, `release-audit-tooling.md`,
`release-audit-updater.md`, `release-audit-service.md`, `release-audit-tester.md`.
