"""timeouts.py - именованные тайминги продукта (аудит #9, §3.6).

Только ИМЕНА: значения фиксируют текущее поведение (юстировка - отдельным
коммитом; аудит: «не менять значения в одном рефакторинге»).

Задействованы в точках, где замена символ-в-символ: tester (SETTLE_*),
tester_probes (FAST/HTTP/WALL_PAD), recommend (SETTLE_BLOB).

Исторический разброс по сайтам (НЕ унифицирован - унификация отдельно):
  curl-класс (tester): -m min(timeout,6), connect 2, outer +5   (= HTTP/WALL_PAD)
  TCP16-20 (tester):   -m min(timeout,6), outer +5              (= HTTP/WALL_PAD)
  ASN (tester):        -m 10, connect 3, outer 15, повтор ~1.2s
  diagnostics:         -m 6, outer +3; DNS-spoof -m 8, outer 12
  DoH-резолв (tester_probes): -m 4, connect 2, outer +5
  games (server):      -m 8, outer 12
  contested (server):  -m 10, outer 15
"""

FAST = 3             # быстрые пробы (QUIC-quirk curl -m, connect-фаза)
DOH = 4              # DoH-резолв dns.google (tester_probes; фолбэк при спуфе)
HTTP = 6             # базовый HTTP-уровень (-m)
SLOW = 10            # долгие пробы (-m; ASN/diagnostics - ждут унификации)
WALL_PAD = 5         # внешний запас процесса поверх -m (subprocess timeout)
CONNECT = 2          # --connect-timeout curl
SETTLE_WINWS2 = 1.5  # прогрев winws2 после спавна (WinDivert отдаёт хендл)
SETTLE_BLOB = 0.8    # прогрев после перезапуска профиля с новым блобом
