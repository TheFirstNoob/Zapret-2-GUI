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
- [ ] VERSION в core/config.py → X.Y (в манифесты portable/lite уходит сам).
- [ ] Ченджлог на рабочем столе дополнен и выверен.
- [ ] Пресеты/списки release-набора актуальны.

## Сборка
- [ ] `python build.py` → exe + `Windows build/Zapret2GUI.zip` + .sha256
- [ ] `python build_portable.py` → Zapret2GUI-portable.zip + .sha256
- [ ] `python build_lite.py` → Zapret2GUI-lite.zip + .sha256
- [ ] `python tools/security/test_updates_security.py` — все зелёные.

## Подпись (обязательно)
- [ ] `python tools/security/sign_release.py --version X.Y --tag Pre-Release-X.Y --key <офлайн-ключ>`
      → release.json + release.json.sig в корне репо (внутри — самопроверка).
- [ ] Отпечаток в выводе = 50DCECF29451 (тот самый ключ).

## Публикация
- [ ] Закоммитить дистрибутивы + release.json + release.json.sig в main.
- [ ] Тег Pre-Release-X.Y → GitHub Release; прикрепить 3 zip + release.json +
      release.json.sig (байт-в-байт те же файлы, что закоммичены).
- [ ] README/описание релиза: SHA256, ссылки.

## После публикации
- [ ] Смоук: манифест по jsDelivr-пути, проверка подписи и хешей.
- [ ] Живой тест апдейтера. Переход 0.8→0.9 — последний на старой логике
      (0.8 ещё без подписи); дальше всё только с проверкой подписи.
- [ ] Синк зеркала `Desktop\Zapret 2 GUI\zapret2_gui` (точечно, не robocopy).
