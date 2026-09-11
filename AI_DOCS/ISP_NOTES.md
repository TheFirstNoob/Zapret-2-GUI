# ISP-специфичные наблюдения (обновлено 2026-09-11, Pre-release 0.6)

> Исторические данные (Zapret 1, 2026-07) — ниже. Актуальная механика Т2 —
> STRATEGY_TRIALS (repeats=7, доля фейков, батареи 09-11).

## ⚠️ ВАЖНО: `default.txt` — универсальная стратегия

**`default.txt` работает у ВСЕХ протестированных провайдеров/регионов:**
- Новороссийск («Новый Интернет»)
- Ижевск (Марк-ИТТ)
- Воронеж (JustLan)
- СПб (Т2 мобильный / Skynet дома)

Ранее считалось, что разные DPI требуют разных стратегий (см. OLD_LOGS ниже).
Это опровергнуто — `default.txt` универсален.

### Структура default.txt
```
7 блоков: Discord Voice, Discord Media TCP, Discord TCP tls,
Google TCP tls, General TCP, QUIC Google, QUIC General
```

---

## Доступные блобы (blobs/) — актуально 2026-09-11

Полный список генерируется селектором GUI (ручной приоритет, автопрефикс
цифровых имён, стоп-лист — см. AGENTS снапшот). Ключевые:
| Блоб | Размер | Статус на Т2 |
|------|--------|--------------|
| `tls_clienthello_www_google_com.bin` | 681 | эталон, по умолчанию |
| `tls_clienthello_sochi_park.bin` | 244 | боевой запасной (проверен 09-10) |
| `tls_clienthello_mail_ru.bin` / `vk_com` / `iana_org` / `hcaptcha_com` / `alfabank_ru` | 235-517 | проверены 6/6 (09-11) |
| `tls_clienthello_max_ru.bin` | 664 | работал в general |
| `tls_clienthello_rutracker_org_kyber.bin` | 1787 | НЕ использовать для fake (огромный, доля фейков падает) |
| `quic_initial_www_google_com.bin` | 1200 | QUIC Google |

---

## OLD_LOGS — исторические данные (Zapret 1)

До нахождения универсальной стратегии каждый провайдер требовал своего подхода:

| Город / ISP | Zapret1 стратегия | Особенность |
|-------------|-------------------|-------------|
| Новороссийск | `fake` + `tls_mod=rnd,dupsid` + `ip_id=zero` | repeats=10, autottl=2 |
| Ижевск | `fake` + `tls_clienthello_4pda_to.bin` | ALT10 |
| — | `fake+multisplit` + `seqovl=652` | BALANCED |
| — | `fake,fakedsplit` + `pattern=0x00` | ALT |
| — | `fake+multisplit` + `seqovl=681/664` | ALT11 |

**Сейчас все эти стратегии заменены одной — `default.txt`.**

### Соответствие bat → winws2 пресетам (историческое)

| bat-стратегия | winws2 пресет | Статус |
|---------------|---------------|--------|
| DEEP FAKE | `fake-rnd-dupsid.txt` | ✅ Заменён на default.txt |
| ALT10 | `fake-only.txt` | ✅ Заменён на default.txt |
| ALT11 | `alt11-tcp443.txt` | ✅ Заменён на default.txt |
| BALANCED | `fake-multisplit-combo.txt` | ✅ Заменён на default.txt |
| ALT | `fakedsplit-zero.txt` | ✅ Заменён на default.txt |

---

## Типы DPI (историческая справка)

| Тип DPI | Симптом | Рабочая стратегия (до default.txt) |
|---------|---------|-------------------------------------|
| «Новый Интернет» (Новороссийск) | SYN timeout | `multisplit:pos=2,midsld` без fake |
| ТСПУ (пассивный SNI) | TIMEOUT на целевые | `multisplit` + blob + `tcp_ts` |
| JustLan | RST после ClientHello | hostfakesplit + валидный SNI |
| Ростелеком | Обрыв соединения | `fake` only |
| Дом.ру / агрессивный DPI | TIMEOUT на целевые | `fake` + `multisplit` + seqovl |

**Сейчас все покрываются `default.txt`.**

---

## Доступные пресеты (presets/) — актуально 2026-09-11 (11 release)

| Пресет | Описание |
|--------|----------|
| `default.txt` | **Универсальная стратегия** — 7 блоков, все порты |
| `default-alt.txt` | default + discord-фейки с `tls_mod=rnd,dupsid` (стабилен 3/3) |
| `auto.txt` | default + автопереключение стратегий (circular) |
| `tcpmd5-fake.txt` | fake + tcp_md5 (кандидат №1 для сетей с фингерпринтом) |
| `fake-only.txt` | Pure fake Google TLS для тестов |
| `fakedsplit.txt` | Fake + fakedsplit |
| `hostfakesplit.txt` | Hostname fake + split |
| `fake-disorder.txt` | Fake + disorder (кастомная lua) |
| `fake-multidisorder.txt` | Fake + multidisorder |
| `multisplit-pure.txt` | Чистый multisplit |
| `multisplit-seqovl.txt` | Multisplit с seqovl |

> exp-/cand- стенды (скрыты из GUI и дистрибутивов) — не для пользователей.
