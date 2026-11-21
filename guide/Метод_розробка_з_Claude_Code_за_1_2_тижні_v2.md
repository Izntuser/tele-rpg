# Метод: розробка з Claude Code за 1-2 тижні (v2)

Nov 14, 2026 · @John Michael Dou

## Принцип

Єдиний обмежений ресурс це контекстне вікно агента. Стан проєкту живе у файлах і git, а не в розмові; кожна сесія робить рівно один стейдж і залишає репозиторій у робочому стані; готовність визначає скрипт, а не самооцінка моделі; людина приймає рішення на початку і перевіряє результат, а не супроводжує кожен крок. Головна сесія ніколи не пише код сама: вона тімлід, код пишуть виконавці. Один проєкт веде одна людина від інтерв'ю до здачі.

| Етап | Що робиться | Результат | Хто |
| --- | --- | --- | --- |
| 0 | Середовище, шаблон репозиторію | CLAUDE.md, docs/, scripts/, .claude/agents/ | один раз на команду |
| 1 | Інтерв'ю: Claude допитує людину | docs/ARCHITECTURE.md, docs/DECISIONS.md | людина + Opus, plan mode |
| 2 | Стейджі з критеріями готовності і класами складності | docs/stages.json, docs/STAGES.md | людина + Opus |
| 3 | Тімлід роздає стейджі виконавцям, рев'ює, мержить | змержені стейджі, docs/LEAD-LOG.md | Opus лід; Sonnet, Codex, Opus виконавці |
| 4 | Автономний прогін без людини | docs/PROGRESS.md, docs/NIGHT-REPORT.md | агенти на окремій машині |
| 5 | Чистка CLAUDE.md, TODO, DECISIONS, PROGRESS | короткий стартовий контекст | людина, раз на тиждень |

**Що змінилось у v2** (за статтями Anthropic "Building effective agents" і "Effective harnesses for long-running agents"):

- Стан стейджів у `docs/stages.json`, а не в Markdown; агент міняє лише поле `passes`, і лише через скрипт.
- Стартова рутина кожної сесії: pwd, git log, PROGRESS.md, init.sh, smoke-тест.
- `init.sh`, `docs/PROGRESS.md` (append-only лог сесій), `docs/LEAD-LOG.md` (рішення тімліда), `scripts/check-stage.sh` (перевірка як код).
- Два режими провалу названі явно і закриті правилами: "взяв забагато" і "оголосив готовим завчасно".
- Браузерна перевірка як користувач для стейджів з `ui: true`.
- Драбина паралелізму: за замовчуванням лід + один виконавець послідовно; паралель лише при 3+ незалежних стейджах.
- Маршрутизація виконавців за полями `complexity` і `risk`, які ставить планувальник, а не судження тімліда.
- Подвійне рев'ю різними моделями лише для `risk: sensitive`.

## Етап 0: середовище

Мета: агент працює годинами без робочого ноутбука і без ручного підтвердження кожної команди, а свіжа сесія за хвилину розуміє, де проєкт зупинився.

**Підписка і моделі.** Claude Max (5x або 20x). Opus для планування, рев'ю, тімліда і стейджів `complexity: high`; Sonnet для `medium`; Codex або Sonnet для `low`; Haiku для тонких обгорток. На нову модель переходити одразу після релізу.

**Машина.** Окремий Linux-сервер або міні-ПК, 32 GB RAM, Docker. Один користувач Linux на одного розробника і одну підписку. Лише staging-секрети. Налаштування в додатку.

**Структура репозиторію:**

```markdown
CLAUDE.md                 # 30-50 рядків: стек, команди, правила, стартова рутина
AGENTS.md                 # симлінк на CLAUDE.md, його читає Codex
init.sh                   # підняти все однією командою: docker, залежності, міграції, dev-сервер
docs/
  ARCHITECTURE.md         # відповіді з інтерв'ю (етап 1)
  DECISIONS.md            # рішення і причини, по рядку
  stages.json             # стан стейджів: джерело правди для агентів (етап 2)
  STAGES.md               # те саме людською мовою, генерується з JSON
  PROGRESS.md             # append-only: кожна сесія дописує 3-5 рядків
  LEAD-LOG.md             # append-only: рішення тімліда (dispatch, review, merge, fallback)
  TODO.md                 # черга для наступного агента і "Needs human"
  screens/                # скріншоти UI-стейджів <id>.png
scripts/
  check-stage.sh          # запускає dod_command і browser_check стейджу; --mark ставить passes
  smoke.sh                # 30-секундна перевірка, що проєкт живий (health endpoint + один e2e)
.claude/
  agents/                 # stage-worker, stage-reviewer, codex-worker, codex-reviewer
  settings.json           # allowlist, worktree.baseRef
.worktreeinclude          # .env та інші gitignored-файли для worktree
.gitignore                # + .claude/worktrees/
```

**Шаблон CLAUDE.md v2.** Тест для кожного рядка: якщо його прибрати, агент зробить конкретну помилку?

```markdown
# Project: <name>

## Stack
Next.js 15 (app router), Nest.js API, PostgreSQL 16 via Prisma, Docker Compose for local.

## Commands
- bootstrap: ./init.sh            (idempotent: docker up, install, migrate, dev server)
- smoke: scripts/smoke.sh         (must pass before you start any work)
- test: pnpm test
- lint: pnpm lint && pnpm typecheck
- stage check: scripts/check-stage.sh <id>        (runs the stage's definition of done)
- stage done:  scripts/check-stage.sh <id> --mark  (the ONLY way to set passes=true)

## Session start (every session, in this order)
1. pwd (you must be inside a git checkout; if the directory is gone, stop and report)
2. git log --oneline -15
3. tail -40 docs/PROGRESS.md
4. ./init.sh, then scripts/smoke.sh. If smoke fails, fixing it IS your task; do not
   start new work on a broken base.
5. Read docs/ARCHITECTURE.md and your stage in docs/stages.json.

## Rules
- One stage per session. Never start a second stage, even if context remains.
- docs/stages.json is NEVER edited by hand. The only allowed change is
  scripts/check-stage.sh <id> --mark after the check passes. Never delete, weaken or
  rewrite dod_command, browser_check or test_steps. This is not negotiable.
- Anything outside the current stage: one line in docs/TODO.md, not code.
- Every change has a test. Full suite green before commit.
- Never edit .env or secrets. Never run destructive git commands.

## Session end (every session)
1. Commit with a conventional message. Repo must be mergeable: no broken tests, no
   half-done files.
2. Append to docs/PROGRESS.md: date, stage id, what was done, what is left, anything
   broken or surprising. 3-5 lines.
3. If you are running low on context: stop early, commit, write PROGRESS, and report
   the stage as PARTIAL. A clean partial beats a messy "done".
```

**Скільки коштує стартова рутина.** Кроки 1-3 це кілька сотень токенів. `init.sh` і `smoke.sh` це 1-2 хвилини і 1-3 тисячі токенів на сесію. Одна сесія, яка півгодини будує на поламаній базі, коштує більше, ніж тиждень таких перевірок.

**Дозволи.** Allowlist у `.claude/settings.json`, або `--dangerously-skip-permissions` лише на ізольованій машині без продакшн-секретів.

## Етап 1: інтерв'ю і spec

Задачу клієнта не передають агенту напряму. Спочатку Claude допитує людину, потім записує відповіді у файл, і цей файл читають усі наступні агенти. Режим: plan mode (Shift+Tab двічі або `claude --permission-mode plan`), Opus. Якщо домен незнайомий, перед інтерв'ю попросіть Claude пояснити предметну область і типові рішення в звичайному режимі.

**Промпт 1.1: інтерв'ю**

```markdown
You are the lead architect on this project. Below is the raw brief from the client.
Do NOT write any code and do NOT propose an architecture yet.

First, interview me. Use the AskUserQuestion tool so I can pick from options.
Ask at least 50 questions in total, in batches of 4-6, covering in this order:
1. Business goal and who the users are; what "done" means for the client
2. Scope: must-have vs nice-to-have vs explicitly out of scope
3. Data model: entities, relationships, volumes, retention
4. Integrations and external APIs, auth, payments
5. Non-functional: load, security, compliance, languages, mobile
6. Infrastructure: hosting, CI/CD, environments, existing code we must reuse
7. UX: pages/screens, roles, admin needs, design source (Figma? none?)
8. Delivery: what the client sees first, demo cadence, acceptance criteria

For every question give 2-4 concrete options plus your recommended default,
so I can answer fast. Skip questions the brief already answers.
When you have no more material questions, say INTERVIEW COMPLETE and stop.

<brief>
...paste the client brief here...
</brief>
```

**Промпт 1.2: запис spec** (та сама сесія, після INTERVIEW COMPLETE)

```markdown
Now write docs/ARCHITECTURE.md based on everything we discussed. Structure:

1. Goal and users (5 lines max)
2. Scope: in / out, as two lists
3. Architecture: components, how they talk, why this choice over the obvious alternative
4. Data model: entities with key fields and relations
5. API surface: list of endpoints or server actions with one line each
6. Screens/pages with the role that sees each
7. Non-functional requirements and how each is satisfied
8. Infrastructure and environments
9. Open questions for the client (things I could not answer)
10. Verification: how we will prove the whole system works end to end
   (the exact command or script, e.g. `pnpm test:e2e`, and what it checks)

Rules: name concrete files, packages and interfaces. No marketing language.
If you had to assume something, mark it [ASSUMPTION].
Then write docs/DECISIONS.md with the 5-10 key decisions, one line each: decision, reason.
```

**Промпт 1.3: коротка версія** (лендінг, невеликий сайт, одна фіча)

```markdown
/plan
Here is the task: <task>. Interview me with AskUserQuestion, 10-15 questions max,
then write the plan to docs/ARCHITECTURE.md and wait for my approval before coding.
```

Після запису spec: `/clear`.

## Етап 2: стейджі

Стейдж це одиниця контексту: вміщається в одну сесію без компакції і закінчується перевіркою, яку запускає скрипт. Стан стейджів зберігається в JSON: модель значно рідше "підправляє" JSON під себе, ніж Markdown, а скрипти можуть його читати. Всі стейджі стартують з `passes: false`, тому повний обсяг видно з першого дня і агент не може "побачити прогрес і вирішити, що все готово".

**Схема `docs/stages.json`** (один елемент для прикладу):

```markdown
{
  "stages": [
    {
      "id": "S03",
      "goal": "Orders API: create, list, get, with validation",
      "depends_on": ["S01", "S02"],
      "files": ["apps/api/src/orders/**", "packages/db/prisma/schema.prisma"],
      "complexity": "medium",          // low | medium | high
      "risk": "normal",                // normal | sensitive (auth, payments, migrations, PII)
      "ui": false,                     // true => browser_check is required
      "dod_command": "pnpm test --filter api -- orders",
      "browser_check": null,           // e.g. "pnpm e2e --grep @S07" for ui stages
      "test_steps": [
        "POST /orders with valid body returns 201 and an id",
        "POST /orders with unknown customer returns 400",
        "GET /orders?customer=X lists only that customer's orders"
      ],
      "passes": false,
      "attempts": 0,
      "blocked_reason": null
    }
  ]
}
```

`complexity` і `risk` ставить планувальник; тімлід маршрутизує за ними механічно (етап 3). `passes`, `attempts`, `blocked_reason` міняються лише скриптом.

**`scripts/check-stage.sh`** (перевірка як код, а не як думка моделі):

```markdown
#!/usr/bin/env bash
set -euo pipefail
ID="${1:?stage id}"; MARK="${2:-}"
J=docs/stages.json
get() { jq -r --arg id "$ID" ".stages[] | select(.id==\$id) | $1" "$J"; }
CMD=$(get .dod_command); UI=$(get '.browser_check // empty')
echo "== $ID dod: $CMD"; bash -c "$CMD"
if [ -n "$UI" ]; then echo "== $ID browser: $UI"; bash -c "$UI"; fi
echo "== $ID PASSED"
if [ "$MARK" = "--mark" ]; then
  tmp=$(mktemp)
  jq --arg id "$ID" '(.stages[] | select(.id==$id) | .passes) = true' "$J" > "$tmp" && mv "$tmp" "$J"
  echo "== $ID marked passes=true"
fi
```

**Промпт 2.1: стейджі** (нова сесія, plan mode, Opus)

```markdown
Read docs/ARCHITECTURE.md and docs/DECISIONS.md.

You are the engineering manager. Split the implementation into 6-15 stages and write
them to docs/stages.json using exactly the schema in scripts/stages.schema.json.
Then generate docs/STAGES.md as a human-readable summary of the same data.

Constraints:
- A stage fits one agent session without running out of context: roughly 5-15 files.
  If bigger, split it.
- Each stage leaves the repo working and tested. depends_on must be acyclic.
- S01 is always: repo skeleton, Docker Compose, CI, test runner, lint, init.sh that
  brings everything up idempotently, scripts/smoke.sh that proves the app is alive,
  scripts/check-stage.sh, and one trivial end-to-end test. Nothing else.
- An early stage holds all shared contracts (DB schema, API types, shared packages)
  so parallel stages build on the same base.
- For every stage: goal, files, dod_command (a real command that exits non-zero on
  failure), 3-6 test_steps written as observable behaviour, complexity, risk, ui.
- ui: true requires browser_check: a Playwright test that walks the screen as a user
  and saves a screenshot to docs/screens/<id>.png. Do not use native alert()/confirm()
  anywhere in the UI; agents cannot see them.
- risk: sensitive for anything touching auth, payments, migrations on existing data,
  personal data, or public API contracts.
- All stages start with passes: false.
- Before writing, tell me where you expect agents to struggle and what rule or context
  would prevent it; put that into the stage's test_steps or into CLAUDE.md.

Do not start implementing.
```

**Що перевірити людині в stages.json:**

- `dod_command` кожного стейджу реально падає, якщо функціоналу немає (запустіть один-два до початку роботи).
- Немає стейджу "зробити весь бекенд".
- Паралельні стейджі не перетинаються по `files`.
- `risk: sensitive` стоїть скрізь, де має стояти; тут краще перестрахуватись.
- `complexity` не завищена повсюдно: якщо все high, маршрутизація не працює.

**Промпт 2.2: один стейдж за раз** (базовий режим; головна сесія і тут не кодить)

```markdown
You are the tech lead; you do not write application code. Read docs/stages.json and
docs/LEAD-LOG.md. Pick the first stage with passes:false whose depends_on all pass.
Launch the worker that matches its complexity/risk (routing table in CLAUDE.md), wait
for its report, launch stage-reviewer on the branch, merge on APPROVE, run
scripts/check-stage.sh <id> --mark on the merged result, append one line to
docs/LEAD-LOG.md, and stop. One stage only.
```

Після кожного стейджу `/clear` і той самий промпт знову.

## Етап 3: тімлід, виконавці, рев'ю

Головна сесія завжди тімлід і ніколи не пише код: так її контекст лишається малим, а код завжди проходить через незалежне рев'ю. Скільки виконавців запускати одночасно, вирішує драбина, а не звичка.

| Рівень | Коли | Що запускається |
| --- | --- | --- |
| 1 (за замовчуванням) | Завжди, поки немає причини для 2 | Лід + один виконавець за раз, послідовно, worktree не обов'язковий |
| 2 | Є 3+ незалежні стейджі з неперетинними `files` | До 4 виконавців паралельно, кожен у своєму worktree, лід мержить |
| 3 | Виконавцям справді треба спілкуватись між собою | Agent Teams (experimental); рідко |

Перехід на рівень 2 виправданий, коли він виміряно скорочує календарний час; якщо зростають мерж-конфлікти або повторні раунди рев'ю, повертайтесь на 1.

**Маршрутизація** (механічна, за полями з stages.json; таблиця копіюється в CLAUDE.md):

| complexity | risk | Виконавець | Рев'ю |
| --- | --- | --- | --- |
| low | normal | codex-worker | stage-reviewer |
| medium | normal | stage-worker (Sonnet) | stage-reviewer |
| high | normal | stage-worker (Opus) | stage-reviewer |
| будь-яка | sensitive | stage-worker (Opus) | stage-reviewer + codex-reviewer, мерж лише при двох APPROVE |

**Підготовка репозиторію (один раз):** `.claude/worktrees/` у `.gitignore`; `.worktreeinclude` з `.env`; `"worktree": {"baseRef": "head"}` у settings.json, якщо будуєте на незапушеній роботі.

**`.claude/agents/stage-worker.md`**

```markdown
---
name: stage-worker
description: Implements exactly one stage from docs/stages.json in an isolated worktree, with tests, and reports back. Use for any implementation stage.
model: sonnet
isolation: worktree
---

You implement one stage. You will be told the stage id. Follow CLAUDE.md to the letter,
including the Session start and Session end routines.

1. Session start routine (pwd, git log, PROGRESS, init.sh, smoke). Broken smoke = your
   first job; do not build on a broken base.
2. Read your stage in docs/stages.json: goal, files, test_steps, dod_command, browser_check.
3. Implement the stage, tests alongside. Stay inside the listed files; anything else
   goes to docs/TODO.md.
4. Run lint, typecheck, full test suite. Then scripts/check-stage.sh <id> (without --mark).
   Fix until it passes. Do not touch dod_command, browser_check or test_steps.
5. For ui stages: run browser_check yourself and look at docs/screens/<id>.png before
   declaring success.
6. Session end routine: commit, append to docs/PROGRESS.md. Do not merge.
7. If context is running low or the stage turns out larger than expected: commit what
   is clean, write PROGRESS, report PARTIAL with what remains.

Report under 15 lines: result (DONE / PARTIAL / BLOCKED), check-stage output summary,
branch name, attempts, blockers. No code in the report.
```

**`.claude/agents/stage-reviewer.md`**

```markdown
---
name: stage-reviewer
description: Reviews a stage branch against docs/stages.json and ARCHITECTURE.md before merge. Read-only. Use after every worker.
model: opus
tools: Read, Grep, Glob, Bash
---

You review a branch produced by another agent. You did not write this code; be critical.
1. Run scripts/check-stage.sh <id> yourself on the branch. If it fails: REQUEST CHANGES.
2. Walk every test_step of the stage and confirm a test or the browser check covers it.
3. Check: follows ARCHITECTURE.md and DECISIONS.md; tests test behaviour, not
   implementation; input validation, auth, secrets; nothing touched outside the
   stage's files; for ui stages, open docs/screens/<id>.png and judge it as a user.
Output: APPROVE or REQUEST CHANGES, then a numbered list of concrete issues with
file:line. Max 20 lines.
```

**Промпт 3.1: тімлід** (головна сесія, Opus; рівень 1 і 2 в одному промпті)

```markdown
You are the tech lead. You never write application code; you delegate, review, merge
and log. Read docs/stages.json, docs/LEAD-LOG.md and tail -40 docs/PROGRESS.md.

Loop until no stage can be started:
- Candidates: stages with passes:false, blocked_reason null, all depends_on passing.
- Parallelism: if 3 or more candidates have non-overlapping `files`, run up to 4 at
  once with worktrees for your agents. Otherwise run exactly one at a time.
- Route each stage by the routing table in CLAUDE.md (complexity, risk).
- Before every dispatch append one line to docs/LEAD-LOG.md:
  <timestamp> DISPATCH <id> -> <worker> (<reason in 5 words>)
- When a worker reports: launch stage-reviewer on its branch. For risk:sensitive also
  launch codex-reviewer. Log each verdict in LEAD-LOG.
- APPROVE (both, for sensitive): merge into the current branch, run the full test suite
  and scripts/check-stage.sh <id> --mark on the merged result, delete the worktree,
  log MERGED <id>.
- REQUEST CHANGES: send the issues to a new worker of the same type with the branch
  name. Max 2 review rounds per stage; then set blocked_reason via
  scripts/block-stage.sh <id> "<reason>" and move on. Log it.
- PARTIAL from a worker: merge if check-stage passes on the partial; otherwise leave
  the branch, log PARTIAL <id>, and re-dispatch next loop with the worker's notes.
- FALLBACK from codex-worker: re-dispatch to stage-worker. Log it.
- Merge conflict: resolve if trivial, else block the stage and log.

Keep your own context small: never read workers' diffs, only reports and verdicts.
Finish with a status table: id, passes, worker, rounds, blocked_reason.
```

`scripts/block-stage.sh` це три рядки jq, які ставлять `blocked_reason` і інкрементують `attempts`; лід теж не править JSON вручну.

## Етап 3б: Codex як дешевий виконавець і другий рев'юер

Підписка ChatGPT дає другий незалежний пул лімітів. Codex бере стейджі `complexity: low` і дає другу думку на sensitive-стейджах: рев'ю іншим сімейством моделей ловить інші помилки, ніж самоперевірка.

**Підключення:** `npm i -g @openai/codex`; `codex login --device-auth` (у ChatGPT увімкнути "Enable device code sign-in for Codex" у Settings > Security або в адмін-панелі workspace); `~/.codex/config.toml` з `approval_policy = "never"`, `sandbox_mode = "workspace-write"`; у репозиторії `ln -s CLAUDE.md AGENTS.md`.

**`.claude/agents/codex-worker.md`**

```markdown
---
name: codex-worker
description: Runs one low-complexity stage via Codex CLI inside an isolated worktree. Use for complexity:low, risk:normal stages.
model: haiku
isolation: worktree
tools: Bash, Read
---
You are a thin wrapper around Codex. You will receive a stage id.
1. Session start routine from CLAUDE.md (pwd, git log, PROGRESS, init.sh, smoke).
2. Extract the stage from docs/stages.json. Write a self-contained brief to
   .codex-brief.md: goal, files, test_steps, dod_command, the Rules section of
   AGENTS.md, and "do not touch anything outside these files; do not edit
   docs/stages.json".
3. Run: codex exec --sandbox workspace-write --skip-git-repo-check \
   --output-last-message .codex-report.txt "$(cat .codex-brief.md)"
   with a 40 minute timeout.
4. Run scripts/check-stage.sh <id> yourself. If it fails, run Codex once more with the
   failure output appended. Max 2 attempts.
5. On success: commit, append to docs/PROGRESS.md. Report DONE with check output,
   branch, attempts. On rate limit or two failures: report FALLBACK.
```

**`.claude/agents/codex-reviewer.md`** (другий голос для sensitive)

```markdown
---
name: codex-reviewer
description: Independent read-only review of a stage branch by Codex. Use only for risk:sensitive stages, in addition to stage-reviewer.
model: haiku
tools: Bash, Read
---
You will receive a stage id and a branch name. Build a brief: the stage entry from
docs/stages.json, ARCHITECTURE.md sections relevant to its files, and the instruction
"Review branch <branch> for this stage. Focus on security, data integrity, auth and
migration safety. Output APPROVE or REQUEST CHANGES, then numbered issues with
file:line, max 20 lines." Run:
  codex exec --sandbox read-only --skip-git-repo-check \
    --output-last-message .codex-review.txt "$(cat .codex-review-brief.md)"
Return the file content verbatim.
```

**Правила:** бриф самодостатній, Codex не бачить сесію Claude; circuit breaker обов'язковий; перший тиждень фіксуйте частку стейджів, закритих з першої спроби, окремо по кожному типу виконавця, і пересувайте межу low/medium за цими цифрами; Plus-плану вистачає на рев'ю і дрібні стейджі вдень, нічні прогони потребують Pro.

## Етап 4: автономна робота

Два режими провалу довгих прогонів, і що їх закриває:

| Провал | Як виглядає | Що закриває |
| --- | --- | --- |
| Взяв забагато | Агент тягне кілька фіч одразу, вичерпує контекст посеред роботи, залишає напівзбудоване без нотаток; наступна сесія вгадує і ремонтує | Один стейдж на сесію; правило PARTIAL при нестачі контексту; PROGRESS.md і git як стан; smoke на старті |
| Оголосив готовим завчасно | Агент бачить накопичений прогрес і вирішує, що проєкт завершено; або позначає стейдж готовим без перевірки | Всі стейджі `passes: false` на старті; `passes` ставиться лише через check-stage.sh --mark; завершення визначається jq, а не думкою агента |

**Три способи не зупинятись:**

| Спосіб | Як | Плюси / мінуси |
| --- | --- | --- |
| Промпт "вирішуй сам" | Промпт 4.1 | Нуль налаштувань; агент все одно може зупинитись через кілька годин |
| `/goal` або Stop hook | Умова: `jq '[.stages[] \| select(.passes==false and .blocked_reason==null)] \| length' docs/stages.json` дорівнює 0 | Офіційний механізм; в межах одного контексту |
| Ralph loop | Зовнішній цикл, свіжа сесія `claude -p` на кожну ітерацію; стан у файлах і git | Багатогодинні прогони; потрібен ліміт ітерацій |

**Промпт 4.1: додаток до промпту тімліда для роботи без людини**

```markdown
I will be away for the next 8 hours. Do not stop to ask me questions.
When you face a decision:
- if ARCHITECTURE.md or DECISIONS.md answers it, follow them;
- otherwise pick the simplest option that keeps tests green, and append one line to
  docs/DECISIONS.md: "[AUTO] <decision>: <reason>". I will review these in the morning;
- only if the decision is irreversible (deleting data, changing a public API contract,
  paying for a service) write it to docs/TODO.md under "## Needs human", block the
  stage with scripts/block-stage.sh, and move on.
You are done only when
  jq '[.stages[] | select(.passes==false and .blocked_reason==null)] | length' docs/stages.json
prints 0 and the full test suite passes on the merged branch. Your opinion that the
project looks finished does not count; only that number does.
Then write docs/NIGHT-REPORT.md: stages merged, stages blocked and why, [AUTO]
decisions taken, what needs me. Then stop.
```

**Правило TODO.md.** Агент, який посеред стейджу побачив щось варте уваги, не робить це, а записує один рядок; свіжий агент потім робить це з чистим контекстом.

```markdown
# TODO
## Needs human
- [ ] ...
## Next agent
- [ ] (S04) extract PriceCalculator into shared package, used by 3 modules
- [ ] (S06) add index on orders.customer_id, query is slow in tests
```

**Ralph loop мінімально** (на окремій машині, в tmux або systemd):

```markdown
#!/usr/bin/env bash
# ralph.sh: fresh lead session per iteration; state lives in stages.json, PROGRESS.md, git
set -e
MAX=${MAX:-30}
left() { jq '[.stages[] | select(.passes==false and .blocked_reason==null)] | length' docs/stages.json; }
for i in $(seq 1 $MAX); do
  echo "=== iteration $i, stages left: $(left) ==="
  [ "$(left)" -eq 0 ] && { echo done; exit 0; }
  claude -p "$(cat docs/LOOP-PROMPT.md)" --permission-mode acceptEdits --max-turns 200 || true
  sleep 30
done
```

`docs/LOOP-PROMPT.md` це промпт 3.1 плюс 4.1. Офіційний плагін робить те саме через Stop hook: `/plugin install ralph-wiggum@claude-plugins-official`, потім `/ralph-loop "<prompt>" --max-iterations 30`. Завжди ставте ліміт ітерацій.

**Верифікація замість читання коду.** Вранці людина дивиться NIGHT-REPORT.md, LEAD-LOG.md, скріншоти в `docs/screens/` і клацає staging. Вибіркове читання коду лишається для `risk: sensitive`.

## Етап 5: гігієна контексту

Раз на тиждень або після кожних 2-3 нічних прогонів, 1-2 години. Файли, які агенти читають на старті, роздуваються самі собою.

- [ ] CLAUDE.md: для кожного рядка "якщо прибрати, агент помилиться?" Ні = видалити або перенести.
- [ ] Правила, дописані агентами: залишити лише ті, з якими згодні.
- [ ] PROGRESS.md: записи старші за тиждень згорнути в 3-5 рядків підсумку; агенти читають лише хвіст, але файл не має рости безкінечно.
- [ ] LEAD-LOG.md: переглянути FALLBACK і PARTIAL: це сигнал, що `complexity` стейджу була занижена або стейдж завеликий. Старі записи в архів.
- [ ] stages.json: стейджі з `passes: true` перенести в `docs/stages-archive.json`; заблоковані або розбити на менші, або вирішити руками; TODO.md згрупувати в нові стейджі.
- [ ] DECISIONS.md: рядки \[AUTO\] переглянути; неправильні перетворити на стейдж "переробити X".
- [ ] ARCHITECTURE.md: звірити з кодом.
- [ ] `git worktree list`, `git branch`: залишки видалити.
- [ ] Стартовий контекст (CLAUDE.md + файли з рутини) не більше 20-30k токенів; `/context`.

**Промпт 5.1: чистка силами Claude** (свіжа сесія, Opus)

```markdown
Read CLAUDE.md, docs/ARCHITECTURE.md, docs/DECISIONS.md, docs/TODO.md, docs/PROGRESS.md,
docs/LEAD-LOG.md and docs/stages.json.
Act as a skeptical editor. Propose, do not apply:
- CLAUDE.md: keep only rules whose removal would cause a concrete mistake. Target under 50 lines.
- PROGRESS.md: collapse entries older than 7 days into a 5-line summary at the top.
- LEAD-LOG.md: list every FALLBACK and PARTIAL with the stage's complexity; suggest
  which stages were misclassified or too big.
- stages.json: list passed stages to archive; for blocked ones propose a split.
- TODO.md: drop items already done (check the code); group the rest into proposed
  new stages with a dod_command each.
- DECISIONS.md: group [AUTO] lines, flag those contradicting ARCHITECTURE.md.
Show the diff as a plan. Wait for my approval.
```

## Фідбек клієнта у стейджі

Після першої збірки найдорожча робота це прохід по інтерфейсу з помітками. Її віддають клієнту і агенту.

1. Клієнт записує екран з голосом, клацаючи staging.
2. Відео перетворюється на транскрипт і кадри (ffmpeg кожні 2-3 секунди, whisper для аудіо).
3. Промпт 6.1 перетворює це на нові елементи stages.json, далі звичайний етап 3.

**Промпт 6.1**

```markdown
In feedback/<date>/ there is transcript.txt and frames/*.png from the client's screen
recording (timestamps in file names). Map every remark to a screen and component.
Produce docs/FEEDBACK-<date>.md: a table with remark, screen, file(s), severity
(bug / UX / wish), proposed fix in one line.
Then append bugs and UX items to docs/stages.json as new stages following the schema:
passes false, ui true where a screen is involved, a dod_command or browser_check that
reproduces the complaint and fails today. Wishes go to docs/TODO.md.
Do not implement anything.
```

## Додаток: налаштування сервера

Ubuntu/Debian; sudo лише для apt, Docker і глобальних бінарників; авторизація від користувача.

```markdown
# 0. база
sudo apt update && sudo apt install -y git curl tmux build-essential ripgrep jq
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER        # перелогінитись

# 1. Node 22 системно (якщо apt-версія старіша за 20)
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs
sudo npm i -g pnpm @openai/codex

# 2. Claude Code
curl -fsSL https://claude.ai/install.sh | bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc
claude doctor

# 3. авторизація (від користувача, не від root, з живої директорії)
cd ~
claude                               # URL відкрити на ноутбуку
codex login --device-auth            # код на auth.openai.com/codex/device

# 4. зв'язка
claude mcp add --scope user codex -- codex mcp-server

# 5. перевірка
claude -p "say OK"
codex exec --skip-git-repo-check "say OK"
docker run --rm hello-world
free -g && df -h /
```

**Авторизація для автоматики.** Claude: на ноутбуку `claude setup-token`, на сервері `export CLAUDE_CODE_OAUTH_TOKEN=...` у `~/.bashrc` (chmod 600). Codex: перемикач "Enable device code sign-in for Codex" у chatgpt.com/settings/security або в адмін-панелі workspace; запасний варіант `ssh -L 1455:localhost:1455 user@server` і звичайний `codex login`.

**Нічні прогони.** `tmux new -s night`, усередині `./ralph.sh`; відключитись `Ctrl+b d`. Автозапуск через `systemd --user`.

**Безпека і пастки.** Лише staging-секрети; `ufw allow OpenSSH && ufw enable`; Docker-порти на 127.0.0.1; раз на тиждень `git worktree prune` і `docker system prune`. Якщо shell стоїть у видаленому worktree (`.claude/worktrees/agent-...`), будь-яка команда падає з "No such file or directory"; саме тому стартова рутина починається з `pwd`.

## Джерела

- [Building effective agents](https://www.anthropic.com/research/building-effective-agents) (Anthropic): workflows vs agents, routing, orchestrator-workers, evaluator-optimizer, голосування, простота і прозорість
- [Effective harnesses for long-running agents](https://www.anthropic.com/research/effective-harnesses-for-long-running-agents) (Anthropic): feature list у JSON, progress file, init.sh, стартова рутина, браузерна перевірка, два режими провалу
- [Best practices for Claude Code](https://code.claude.com/docs/en/best-practices) (Anthropic): контекст, CLAUDE.md, plan mode, interview-to-spec, subagents, Writer/Reviewer, /batch, headless
- [Run parallel sessions with worktrees](https://code.claude.com/docs/en/worktrees.md) (Anthropic)
- [Subagents](https://code.claude.com/docs/en/sub-agents) і [Agent teams](https://code.claude.com/docs/en/agent-teams) (Anthropic)
- [Codex authentication](https://developers.openai.com/codex/auth) і [Codex pricing](https://developers.openai.com/codex/pricing) (OpenAI)
- [Ralph Wiggum as a software engineer](https://ghuntley.com/ralph/) (Geoffrey Huntley)
- [cc-orchestrator](https://github.com/p3nchan/cc-orchestrator): playbook "Claude оркеструє, Codex виконує"

Попередня версія: [Метод: розробка з Claude Code за 1-2 тижні (v1)](https://claude.ai/artifact/PtuBw2xv6Foygy9Fp3quvS).
