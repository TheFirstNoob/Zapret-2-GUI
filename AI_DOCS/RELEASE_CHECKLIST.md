# Чеклист релиза (Pre-Release X.Y)

> 0.10 выпущен и immutable (тег `3fd25f0`). Актуальный релиз — **0.11**
> (тег `Pre-Release-0.11` → `f29cdb3`, опубликован 2026-11-14; 8 pretty-ассетов,
> подпись `50DCECF29451`). Сборка — из HEAD (1.0.7 + `pos=1,midsld`); архивы
> 27.10 (1.0.6) не публиковать. «Фикс YouTube» в release notes не обещать
> (см. `YOUTUBE_VIDEO_STALL_2026-11.md`).
> **Осталось:** live-приёмка 0.11 (SCM/portable/exe-апдейт/тестер/DNS/Win10).
> Известное ограничение: jsDelivr full exe >20 MB не отдаёт; portable/lite — да.
> Детали — `RELEASE_READINESS_0.11.md`.

## Риск-свип перед сборкой (~30 мин)

Проверять классы отказов на стыках данных × ошибки × внешних систем:

- [ ] **Silent-default → destructive sink:** `except: pass`/`return {}` не
      приводят к записи пустоты в файл/SCM/реестр.
- [ ] **Парные операции:** stop/start, pause/resume, create/delete — в
      try/finally; исключение не оставляет защиту выключенной.
- [ ] **Клоны вызовов:** одинаковые ветки не расходятся по параметрам
      (например, потерянный `discord_alt`).
- [ ] **Read-modify-write:** SCM/hosts/реестр мутируют только после
      успешного чтения.
- [ ] **Владелец ресурса:** winws2 не запускается дважды (служба/ручной).
- [ ] **Data-loss:** запись user-файлов только с явным payload; невалид —
      ошибка, файл не тронут.

## Разово (сделано)
- [x] Офлайн-ключ подписи создан; копии: бумага + шифрованный архив.
- [x] PUBKEY вшит в core/update_verify.py (отпечаток 50DCECF29451).
- [x] GitHub: 2FA + Immutable Releases + защита main.
- [x] Приватный ключ не в репо (.gitignore + запрет пути в gen-скрипте).

## Перед сборкой
- [ ] Риск-свип выше.
- [ ] VERSION в core/config.py → X.Y (в манифесты portable/lite уходит сам).
- [x] Корневой файл `VERSION` в репо → тот же X.Y: его читает проверка обновлений
      (raw + jsDelivr). Протухший файл = пользователи не увидят обновление.
- [x] `CHANGELOG.md` в репозитории дополнен и выверен (0.11).
- [ ] Код-фриз: `git status` чистый; README/CHANGELOG/docs закоммичены.
- [x] Пресеты/списки release-набора актуальны.
- [ ] 0.11 собирать из HEAD (1.0.7 + `pos=1,midsld`); архивы 27.10 (1.0.6,
      старые пресеты) не публиковать.
- [ ] В release notes не обещать «фикс YouTube»; видео-диагностика — по
      `YOUTUBE_VIDEO_STALL_2026-11.md` (P0: InnerTube/SABR + H3 + метрики).
- [ ] `python tools/check_arg_file.py` зелёный (fail-closed argv↔@conf; в CI).
- [ ] `sign_release.py` берёт ВСЕ 3 архива и проверяет версию/тег/PUBKEY/
      движок внутри архивов (0.11: движок должен быть 1.0.7).
- [x] `release_publish.py --dry-run` — RC=0, 8 pretty-ассетов, VERSION/tag/manifest/runtime/sha256/size сходятся.
- [x] Размеры измерены: portable 17.8 MiB и lite 1.7 MiB проходят jsDelivr;
      full exe-zip 20.5 MiB (21.5 MB) — не проходит. Решение 0.11: GitHub —
      основной источник, portable/lite — зеркало; записано в README/CHANGELOG.
- [ ] **Portable 0.10 → 0.11:** в release notes явно «переустановить portable
      из архива» — первый хоп старым апдейтером не доставляет `python/`
      (runtime-секция manifest работает начиная с 0.11).
- [ ] **Live-приёмка fix batch 2026-11-14** (не unit): install/remove/repair/
      restart службы + failure actions; живой portable-апдейт; тестер/H3/CDN
      на реальной сети; DNS apply/reset на IPv6 + 3+ серверах; Win10/PS5.1.
      Пока не пройдено — не писать в нотах «всё исправлено». Чек-лист —
      `RELEASE_READINESS_0.11.md` §«Live-чек-лист».
- [x] `hosts.txt` актуален - он уезжает во все три сборки (exe-zip рядом
      с exe, portable `app\hosts.txt` - обновляется апдейтером, lite
      `hosts.txt` в корне).

## Сборка
- [ ] build-env: `pip install -r requirements.txt` (нужен `niquests[http3]`;
      spec падает с подсказкой, если стека нет - с 13.10).
- [x] `python build.py` → exe + `Windows build/Zapret2GUI.zip` + .sha256 (0.11 из HEAD)
- [x] `python build_portable.py` → Zapret2GUI-portable.zip + .sha256 (0.11; manifest runtime.rev)
- [x] `python build_lite.py` → Zapret2GUI-lite.zip + .sha256 (внутри: VERSION и
      дата в README; сборка сама прогоняет dry-run всех release-пресетов)
- [x] `python tools/security/test_updates_security.py` — 47 тестов зелёные (включая PUBKEY-гард).

## Подпись (обязательно)
- [x] `python tools/security/sign_release.py --version 0.11 --tag Pre-Release-0.11 --key <офлайн-ключ>`
      → release.json + release.json.sig в корне репо (внутри — самопроверка).
- [x] Отпечаток в выводе = 50DCECF29451 (тот самый ключ).

## Публикация
- [x] **(0.11) Закоммитить дистрибутивы + `.sha256` + release.json + release.json.sig в main ДО тега** (publish создаёт тег от main и не проверяет git-состояние).
- [x] **(0.11) После коммита ещё раз `release_publish --dry-run` — только потом publish.**
- [x] (0.10) Закоммитить дистрибутивы + `.sha256` + release.json + release.json.sig в main.
- [x] (0.10) Тег Pre-Release-X.Y → GitHub Release; в **описание релиза** — SHA256
      всех трёх архивов (печатает sign_release) — README обещает сверку
      «с хешем в описании релиза».
- [x] (0.11) Проверить README/AGENTS/PLAN_WEBVIEW2_FALLBACK на актуальность
      до тега: версия, WebView2, известные особенности.
- [x] (0.11) Релиз опубликован 2026-11-14: тег `Pre-Release-0.11` → `f29cdb3`,
      8 pretty-ассетов; https://github.com/TheFirstNoob/Zapret-2-GUI/releases/tag/Pre-Release-0.11

## После публикации
- [x] Смоук: манифест по jsDelivr-пути, проверка подписи и хешей.
- [x] Живой тест апдейтера (2026-10-10): опубликованный 0.9 portable -> 0.10
      через реальный GitHub: подпись 0.9-клиентом проверена (797 файлов
      применено, юзер-файлы целы). ВАЖНО: кнопка «Обновить» в 0.8/0.9 мертва
      (баг привязки обработчика, починен в 0.10) - эти версии обновляются
      только вручную; предупреждение — в описании релиза.
- [x] Синк live-копии (точечно, не robocopy).
- [ ] **(0.11) Live-приёмка после публикации:** SCM install/remove/repair/restart,
      portable 0.10→0.11, exe-апдейт при живой службе, тестер/H3/CDN, DNS,
      Win10/PS5.1. До неё не писать «всё исправлено».
- [x] SHA256 в описании релиза — по НАШИМ (pretty) именам (не по каноническим),
      чтобы не путать людей. Канонические дубли, если всё же выложены (кейс
      0.10), в нотах помечать как fallback для старых версий.

## Ассеты релиза: политика (с 0.11 — ТОЛЬКО pretty-имена)
История: 0.10 (immutable) выпущен с ОБОИМИ именами каждого архива
(pretty + каноническое) как переходная страховка. Впредь дубли НЕ грузим —
0.10 остаётся исключением, повторять не нужно.

Правило с 0.11:
- На GitHub Release загружаем ТОЛЬКО pretty-имена + их `.sha256`:
  `Zapret2GUI-Full-PyInstaller.zip`, `Zapret2GUI-portable-Recommended.zip`,
  `Zapret2GUI-lite-CMD.zip`, + release.json + release.json.sig. Итого 8 ассетов.
- Канонические имена остаются ТОЛЬКО в git (`Windows build/Zapret2GUI*.zip`):
  это путь jsDelivr-зеркала (запасной источник). Файлы в git НЕ переименовывать.
- Почему безопасно: автообновляться умеют только клиенты 0.10+ (в 0.8/0.9
  кнопка мертва) — они знают pretty (первый кандидат `download_url`);
  канонический кандидат и зеркало остаются страховкой.
- Код апдейтера не меняется: `download_url` = [pretty, каноническое],
  поведение зафиксировано `TestAssetNames` в пакете безопасности.
- **Инструмент:** `python tools/release_publish.py --version X.Y --tag
  Pre-Release-X.Y --notes <ченджлог.md>` — draft → 8 ассетов →
  автопроверка комплектности → publish (prerelease=True). Публикация только
  после успешной проверки: дальше релиз immutable. `--dry-run` — только
  staging без GitHub; `--keep-draft` — остановиться до публикации.
- SHA256-блок в описании релиза инструмент строит по **pretty-именам** —
  канонические имена в нотах не упоминаем (кроме пометки fallback, если
  дубли всё же выложены).
