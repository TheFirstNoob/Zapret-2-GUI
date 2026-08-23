СПРАВОЧНИК БЛОБОВ (бинарные данные для lua-desync)

Приоритет по полезности:
   1. steamcommunity (quic_initial_steamcommunity_com.bin) — новый блоб из 1.9.9e preview,
      замена 4pda (отвалился). Самый актуальный QUIC blob.
   2. google (tls_clienthello_www_google_com.bin) — основной TLS, самый стабильный.
      Используется во всех рабочих пресетах (working, optimal, fake-rnd-dupsid и др.).
   3. 4pda (tls_clienthello_4pda_to.bin) — использовался в 1.9.9d, но по сообщениям
      отвалился. Оставлен для совместимости со старыми конфигами.

Остальные:
  - tls_clienthello_max_ru.bin — TLS для неизвестных доменов (fake-http)
  - tls_clienthello_vk_com.bin — VK (⚠️ может быть сломан: vk.com → редирект на vk.ru)
  - tls_clienthello_iana_org.bin — IANA
  - tls_clienthello_rutracker_org_kyber.bin — Rutracker (с Kyber)
  - stun.bin — STUN (используется как fallback в fake-fakedsplit-alt)
  - quic_initial_www_google_com.bin — QUIC Google (работает)
  - quic_initial_dbankcloud_ru.bin — QUIC dbankcloud (оригинал, хост мёртв)

Примечание: windivert_part.* перенесены в ../lists/. zero_*, quic_short, tls_4pda/quic_icloud
— из оригинальной поставки winws2, не используются в текущих пресетах.
