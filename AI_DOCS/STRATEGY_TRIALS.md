# Каталог испытаний стратегий (STRATEGY_TRIALS)

Правило: результат всегда привязан к сети/провайдеру. «Не сработало на Т2»
≠ «мусор» — пресет остаётся кандидатом для других сетей (AGENTS правило 7).

## Сетка

| Пресет / параметр | Где проверено | Дата | Доступность (сеть) | Вердикт |
|---|---|---|---|---|
| `default` | Т2 СПб (моб.), Новороссийск, Ижевск (Марк-ИТТ), Воронеж (JustLan) | 2026-08 | 84–100% | стабильный, универсальный |
| `auto` (circular) | Т2 СПб | 2026-08-30 | 92.3% | фолбэк; на Т2 выигрыша нет |
| `fake-only` | Т2 СПб / Мегафон Чебоксары | 2026-08 | 90% / 67% | кандидат (движок/сеть-зависим) |
| `hostfakesplit` | Т2 СПб | 2026-08 | 47% | для Т2 слаб, кандидат |
| oob / syndata (эксперименты) | Т2 СПб | 2026-08 | 30–46% | для Т2 отсеяны; КАНДИДАТЫ для других сетей |
| **`tcpmd5-fake`** (fake + tcp_md5) | Т2 СПб | 2026-08-31 | **100% (13/13, чистое окно)** | не хуже default; кандидат №1 для сетей, где plain-fake фингерпринтится |
| **`cand-multidisorder`** (multidisorder:pos=1,midsld на ютубе) | Т2 СПб | 2026-08-31 | **69.2%** (ютуб×4 в флак-окне) | ХУЖЕ default; мех. работает (полигон), SNI-блоки ютуба берёт хуже; кандидат для других сетей |
| **`cand-http-md5`** (HTTP 80: fake_http+autottl+tcp_md5, TLS = default) | Т2 СПб | 2026-08-31 | **100%** (окно чистое) | мех. подтверждён (MD5 + TTL 15 vs 65 + блоб); закрывает дыру «TLS-блоб на 80» |
| **`cand-rndsni`** (tls_mod rnd,rndsni на google_tls) | Т2 СПб | 2026-08-31 | 84.6% (discord×2 в окне) | SNI фейка случайный (полигон); ГЛОБАЛЬНО меняет блоб — влияет и на discord-фейки; кандидат |
| **`cand-fakeddisorder-md5`** (фейк-часть+MD5) | Т2 СПб | 2026-08-31 | 84.6% (ютуб×2 в окне) | MD5 на фейках подтверждён (16 пакетов); на Т2 не лучше default |

## Ориентиры для новых кандидатов

Эвристика приоритета из blockcheck2-экосистемы (Zapret2agent, парсер
`!!!!! AVAILABLE !!!!!`): fakedsplit+tcp_md5 > fakeddisorder+tcp_md5 >
fakedsplit > fakeddisorder > multidisorder > multisplit > syndata > fake.
`tcp_md5` поддерживается нашим lua (zapret-antidpi.lua, `tcp_md5[=hex]`).

## Как тестировать

1. Пресет-кандидат кладём в `presets/` (имя без `test-` префикса, если
   планируем раздавать; без комментариев внутри).
2. Прогон: `python <скрипт> tester.test_profile('<имя>')` (или тестер в GUI).
3. Результат — строка в таблицу выше; при проигрыше пресет НЕ удаляем.
4. Защита после headless-прогона: `service_manager.start(args)`.

## Полигон проверки пакетов (tools/pkt_verify.py, 2026-08-31)

200/000 не отличает «параметр применился» от «перекрыт другим». Инструмент:
pktmon-захват исходящего :443 → тестовый curl → разбор pcapng → для каждого
пакета: TCP-опции, TTL, seq, payload.

Проверено live (Т2, google-блок, www.youtube.com):
| Профиль | Пакетов с MD5 (kind 19) | Фейк-пакет |
|---|---|---|
| default | 0 | [NOP,NOP,TS] |
| tcpmd5-fake | 24 | [NOP,NOP,TS,MD5,NOP,NOP] |

Вывод: tcp_md5 реально применяется на уровне пакета (не мусор и не перекрыт);
SNI фейка = www.google.com (блоб) — виден в захвате. Метод: эталон vs параметр,
сравнение полей; если поле не изменилось — параметр мёртв/перекрыт.

## ipset catchall A/B (Т2, 2026-08-31, тестер с группами rated/control)

| Режим | RATED (покрыто) | CONTROL, пробилось |
|---|---|---|
| default (без ipset) | 87.5% (14/16, i.ytimg флак) | 8/16; заблокированы: telegram×2, x.com, facebook, instagram, linkedin, whatsapp, apns |
| default + ipset | 93.8% (15/16, i.ytimg флак) | 10/16; **x.com и linkedin пробились по IP** |

Вывод: ipset_catchall пробивает CDN-класс (x.com/linkedin — их IP в ipset-all),
но НЕ берёт telegram/facebook/instagram/whatsapp/apns (глубже: MTProto/
IP-блэкхол — под ipset-десинк не попадают или блок не по IP). Рейтинг
профилей теперь честный: CONTROL-домены не искажают network_rate.

## CDN + stateful DPI: ipset A/B (Т2, 2026-08-31, наш CDN-тест с TCP-16-20)

| Провайдер | без ipset (TCP16-20 detected) | + ipset | эффект |
|---|---|---|---|
| AWS (amplifon/optout) | 2/2 | 0/2 | ✅ починено |
| Akamai (mobil) | 1/2 | 0/2 | ✅ починено |
| Cloudflare (esm/justice) | 2/4 | 0/4 | ✅ починено |
| Melbicom / Oracle / Scaleway | 1/1, 1/2, 1/1 | 0 | ✅ починено |
| DigitalOcean / Hetzner / BuyVM / OVH / Vultr | detected | **alive → 0** | ❌ ipset ЛОМАЕТ |
| Azure / Fastly / Gcore / self | 0 | 0 | не резались |

Вывод: грубый ipset чинит stateful-DPI класс (AWS/Akamai/CF/Oracle/
Melbicom/Scaleway), но ломает здоровый трафик в подсетях DO/Hetzner/
BuyVM/OVH/Vultr (ipset-all содержит их диапазоны, десинк вредит). →
Точечный подход: конкретные домены режущихся сервисов в list-general
(с проверкой полигоном, что десинк не ломает). Тест-домены CDN в списки
не добавляем.

## CDN: перебор методов на break-классе (Т2, 2026-09-03, стенды exp-cdn-*)

Break-класс = DO/Hetzner/BuyVM/OVH/Vultr (живы «в голую», но stateful DPI
режет их TCP16-20). Fix-класс = AWS/Akamai/CF/Oracle/Melbicom/Scaleway
(там fake+multisplit убирает DET).

| Метод (применён к break-классу) | break alive | break DET | fix DET |
|---|---|---|---|
| без десинка | 12/12 | 12/12 | 8/9 |
| fake+multisplit (=ipset) | 0/12 | — | 0/9 (лечит) |
| multidisorder:pos=1,midsld | 12/12 | 12/12 | 8/9 (не лечит) |
| fake:nodrop (gentle) | 2/12 (BuyVM) | 2 | — |
| fake+tcp_md5 без сплита | 2/12 (BuyVM) | 2 | — |
| fakedisorder:pos=2:blob=google_tls:tcp_md5 | всё сломал (RATED 0%) | — | — |

Выводы:
1. Лечит stateful-DPI класс только fake+multisplit; multidisorder не ломает,
   но и не лечит; gentle/md5-варианты ломают как сплит.
2. Сегментация по методам бессмысленна — альтернатив методу нет.
3. Break-класс НЕ стабилизируется никак: любой десинк вредит, пользы ноль
   (исключение — BuyVM терпит gentle/md5-fake, но это частный случай).
4. Механизм «стабилизации» = точечные хостлисты fix-класса (уже так) +
   автовердикт: жив «в голую» + DET под десинком → кандидат в list-general;
   умер под десинком → в стоп-лист (не добавлять). Break-класс в списки
   не попадает автоматически.
5. Стенды exp-* / кандидаты cand-* скрыты из GUI списка профилей (server:
   _ui_presets фильтрует префиксы exp-/test-/cand-).