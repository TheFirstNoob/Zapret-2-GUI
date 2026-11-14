# TEAM_PLAYBOOK — как Lead использует агентов (обязательные правила)

> Цель: не перечитывать проект заново каждым агентом, не терять контекст,
> не плодить несогласованности. Данные — в локальном кэше
> `_analysis/team/CONTEXT-PACK.md` и `_analysis/team/ROSTER.md` (gitignored).

## 1. Повторное использование вместо новых агентов

1. **Сначала посмотреть `list_agents` и ROSTER**: если домен уже имеет владельца —
   продолжить его через `send_message` (durable-агент сохраняет контекст даже в
   `inactive`). Новый fresh-агент = повторное чтение проекта и риск расхождений.
2. `subagent_fork` — если задача опирается на историю Lead/сессии.
3. `spawn_teammate` fresh — только для новой предметной области, с промптом:
   «прочитай `AI_DOCS/TEAM_PLAYBOOK.md` + `_analysis/team/CONTEXT-PACK.md`,
   затем только свои файлы; проект целиком не читай».
4. Не запускать двух агентов в одном домене одновременно; параллельность —
   только по disjoint write_scopes.

## 2. Контекст и токены

- Каждый тиммейт читает: (а) TEAM_PLAYBOOK, (б) CONTEXT-PACK, (в) свои файлы
  точечно (grep/read с offset/limit). Полные `AGENTS.md`/доки — только если
  задача меняет правила; обычно хватает выжимки в CONTEXT-PACK §7.
- В промпте — точные file:line/функции и критерии, без «изучи проект».
- Большие логи/отчёты — на диск, в чат только вывод/дифф.
- CONTEXT-PACK обновляется Lead'ом после каждого батча (коммиты, тесты, статусы,
  открытые задачи, владельцы). Это и есть «кэш», который читают новые агенты.

## 3. Постановка задач

- На каждую задачу — shared task (`team_task_create`) с subject/description,
  `write_scopes`, зависимостями; тиммейт claim → работа → complete.
- В описании: цель, ограничения, acceptance, что НЕ делать, свои файлы,
  команда проверки (scoped pytest), формат отчёта (15–25 строк).
- Один проблемный класс на задачу; смежные — в один домен, но отдельным пунктом.

## 4. Проверка и коммиты

- Тиммейт: scoped-тесты + compileall, отчёт `_analysis/.../<ID>.md`, БЕЗ коммитов.
- Lead: ревью диффа, полная батарея (CONTEXT-PACK §3), коммиты по одной проблеме,
  обновление CONTEXT-PACK/ROSTER/доков.
- Живые манипуляции службой/сетью/DNS — только Lead после явного согласия владельца.

## 5. Текущая карта владельцев

См. `_analysis/team/ROSTER.md`. Ключевые домены: служба/процессы —
`fix-proc-service`; тестер/H3/CDN/probe — `fix-tester-stability`;
diagnostics/DNS/games — `fix-diag-data`; updater/portable —
`fix-updater-portable`; launcher/args — `fix-launcher-gamefilter`;
ipset/upstream-данные — `sync-flowseal-ipset` / `sync-dpi-detector`;
YouTube — `traffic-map`/`yt-pipeline`.
