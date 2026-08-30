# SDD ledger — plan: docs/superpowers/plans/2026-08-30-ui-rework.md

## Preflight
- Ruling: work directly on main (user's standing workflow: Desktop copy + GitHub repo main, commits+publish per task) — no worktree.
- Ruling: workdir for implementers = GitHub repo (canonical); Desktop mirror sync after each task.
- Ruling: windows — skill's bash scripts not runnable; emulate manually (workspace/briefs/review packages by hand).


## Task 1
- Task 1: complete (commits 337ddbf..2113d14, review 2 parked)
- Ruling: CSS in Task1 commit kept (new blocks need styles); Task 2 refines via #z1Card/#z2Card (JS rewrites className)
- Ruling: strategy not in status line (JS does not fill it; global constraint); intent met via badge+select; Task 5 may add
- Task 1: minor (deferred): conflictInline as id+class; details header has live status

## Task 2
- Task 2: complete (commit 7832076, CSS only)
- Ruling: lamp styled via actual JS classes (.status-dot-ok/-off, + new .status-dot-fail red), not brief's .dot/.ok/.fail/.off (JS emits status-dot-*; JS untouchable)
- Ruling: .main-grid simplified to 1 column (both cards full-width); .main-card-wide kept as harmless no-op

## Task 2
- Task 2: complete (2113d14..7832076, review clean)
- Task 2: minor (deferred): summary focus-visible отсутствует (Task 6 добавит глобально); .status-dot-fail мёртвый CSS (на будущее); хардкод rgba(255,82,82,.3); .z1-details алиасы дублируют id-селектор

## Task 3
- Task 3: complete (7832076..1be5326, review clean)
- Task 3: minor (deferred): text jump on check (reserve ::before space); pointer-events none redundant; opacity .85 on checked small
- RESUME POINT: next session starts at Task 4 (live blocks per strategy). Briefs: .superpowers/sdd/2026-08-30-ui-rework/task-4..N-brief.md not yet extracted — extract from plan file. Desktop sync done at Task 3 point.

## Task 4
- Task 4: complete (1be5326..db39481, review 1-important-ruled)
- Ruling: Step6 runtime-verification parked — user's GUI pass (Task 7 Step 2) is the runtime gate
- Ruling: custom-verify rows without profile = real gap — fixed 4c0738f (profile='custom')
- Task 4: minor (deferred): custom block active+empty until set_final; _finishLiveProfile non-idempotent (300ms window); safeKey collisions theoretical; no aria-controls (Task 6 a11y)
## Task 4-fix
- Task 4: fix 4c0738f — custom verify profile (reviewer-flagged, server 1-line)

## Task 5
- Task 5: complete (4c0738f..3fdc817, review clean)
- Task 5: minor (deferred): caption case unification (equal vs isBest)

## Task 6
- Task 6: complete (3fdc817..d81ad5e, review clean)
- Task 6: minor (deferred): outline-offset -2px on live-block-head; :focus vs :focus-visible on inputs; dead --font-mono var
