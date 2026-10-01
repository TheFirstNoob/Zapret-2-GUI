# Чеклист релиза (Pre-Release X.Y)

> Заведён 2026-09-21 для 0.9. Подпись обновлений обязательна: без неё апдейтер
> отказывает (fail-closed). Подробности механики — AGENTS.md, блок
> «Безопасность обновлений».

## Разово (сделано)
- [x] Офлайн-ключ подписи создан; копии: бумага + шифрованный архив.
- [x] PUBKEY вшит в core/update_verify.py (отпечаток 50DCECF29451).
- [x] GitHub: 2FA + Immutable Releases + защита main.
- [x] Приватный ключ не в репо (.gitignore + запрет пути в gen-скрипте).

## Перед сборкой
- [x] VERSION в core/config.py → X.Y (в манифесты portable/lite уходит сам).
- [x] Корневой файл `VERSION` в репо → тот же X.Y: его читает проверка обновлений
      (raw + jsDelivr). Протухший файл = пользователи не увидят обновление.
- [x] Ченджлог на рабочем столе дополнен и выверен.
- [x] Пресеты/списки release-набора актуальны.

## Сборка
- [x] `python build.py` → exe + `Windows build/Zapret2GUI.zip` + .sha256
- [x] `python build_portable.py` → Zapret2GUI-portable.zip + .sha256
- [x] `python build_lite.py` → Zapret2GUI-lite.zip + .sha256 (внутри: VERSION и
      дата в README; сборка сама прогоняет dry-run всех release-пресетов)
- [x] `python tools/security/test_updates_security.py` — все зелёные.

## Подпись (обязательно)
- [x] `python tools/security/sign_release.py --version X.Y --tag Pre-Release-X.Y --key <офлайн-ключ>`
      → release.json + release.json.sig в корне репо (внутри — самопроверка).
- [x] Отпечаток в выводе = 50DCECF29451 (тот самый ключ).

## Публикация
- [x] Закоммитить дистрибутивы + `.sha256` + release.json + release.json.sig в main.
- [x] Тег Pre-Release-X.Y → GitHub Release; прикрепить архивы **каноническими
      именами** (`Zapret2GUI.zip`, `Zapret2GUI-portable.zip`,
      `Zapret2GUI-lite.zip`) + их `.sha256` + release.json + release.json.sig
      (байт-в-байт те же файлы, что закоммичены). Имена важны: апдейтер качает
      именно их (core/updater.download_url) — при других именах primary-источник
      даёт 404 и спасает только jsDelivr-зеркало.
- [x] В **описание релиза** вставить SHA256 всех трёх архивов (печатает
      sign_release) — README обещает сверку «с хешем в описании релиза».

## После публикации
- [x] Смоук: манифест по jsDelivr-пути, проверка подписи и хешей.
- [ ] Живой тест апдейтера. Переход 0.8→0.9 — последний на старой логике
      (0.8 ещё без подписи); дальше всё только с проверкой подписи.
- [x] Синк зеркала `Desktop\Zapret 2 GUI\zapret2_gui` (точечно, не robocopy).

## Следующий релиз (0.10+): человекочитаемые имена ассетов
Решение 2026-10-01: релизные ассеты называть понятнее:
`Zapret2GUI-Full-PyInstaller.zip`, `Zapret2GUI-portable-Recommended.zip`,
`Zapret2GUI-lite-CMD.zip` (+ `.sha256`). Сейчас (0.9) оставлено как есть —
релиз immutable.

⚠️ Ловушка: `core/updater.download_url` хардкодит канонические имена для
ОБОИХ источников — primary («releases/download/<tag>/<имя ассета>») и
jsDelivr-зеркало (файлы из git: `Windows build/<имя>`). Поэтому при
переименовании обязательно:
1. `download_url` → **список кандидатов** на primary (новое имя, затем
   каноническое), чтобы и старые, и новые клиенты находили файл.
2. Файлы в `Windows build/` в репо **не переименовывать** (иначе
   0.9-клиенты потеряют и primary, и зеркало — обновление не придёт).
3. Обновить build-скрипты (при желании — pretty-копии для ассетов)
   и этот чеклист.
