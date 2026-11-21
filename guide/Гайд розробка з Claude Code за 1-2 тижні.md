# Гайд: розробка з Claude Code за 1-2 тижні

Nov 3, 2026 · @John Michael Dou

## Суть підходу і де він уже описаний

Підхід Alex T не є його винаходом: це майже точна копія офіційного документа Anthropic [Best practices for Claude Code](https://code.claude.com/docs/en/best-practices) плюс два community-патерни (interview-to-spec і Ralph loop). Головна ідея одна: єдиний обмежений ресурс це контекстне вікно, і весь процес будується так, щоб його не засмічувати.

| Що каже Alex T | Як це називається офіційно | Де читати |
| --- | --- | --- |
| Тільки Claude Code, підписка Max | Claude Code CLI / desktop; тарифи Max 5x і Max 20x | [claude.com/pricing](https://claude.com/pricing) |
| Задай мені 50 питань, потім запиши відповіді в ARCHITECTURE.md | Let Claude interview you, write a spec, start a fresh session to implement | Best practices, розділ Communicate effectively; community: interview-to-spec |
| Plan mode, Claude пропонує варіанти відповідей | Plan mode + AskUserQuestion (Shift+Tab, /plan, claude --permission-mode plan) | Best practices, розділ Explore first, then plan, then code |
| Розбий план на 10 стейджів, щоб не заплутатись у контексті | Context management: /clear між задачами, /compact з інструкціями, короткі сесії | Best practices, розділ Manage your session |
| Ти тімлід, створи 5 сабагентів: фронт, бек, БД | Subagents (.claude/agents/), /batch на 5-30 сабагентів, Agent Teams (experimental) | [Subagents](https://code.claude.com/docs/en/sub-agents), Best practices, розділ Automate and scale |
| Кожен сабагент у своєму git worktree, менеджер мержить | --worktree, isolation: worktree у frontmatter сабагента | [Worktrees](https://code.claude.com/docs/en/worktrees.md) |
| Агент не зупиняється, працює 30-40 годин | Ralph Wiggum loop (Geoffrey Huntley, 2025), офіційний плагін ralph-wiggum, /goal, Stop hooks | [ghuntley.com/ralph](https://ghuntley.com/ralph/), Best practices, розділ Give Claude a way to verify its work |
| Агент записує ідеї в TODO-файл, а робить наступний агент | Task list / todos мирроринг у файл; спільна черга задач в Agent Teams | Spec-driven workflow (community) |
| Раз на тиждень чищу CLAUDE.md і memory | Keep CLAUDE.md short: чи зламається щось, якщо прибрати цей рядок | Best practices, розділ Configure your environment |
| Код не читаю, крім sensitive-проєктів | Writer/Reviewer: свіжий контекст рев'ює без упередження; verification subagent | Best practices, розділ Automate and scale |
| Окремий мінікомп, щоб працювало нон-стоп | Headless режим claude -p, фонові сесії, Claude Code on the web | [Headless](https://code.claude.com/docs/en/headless) |

Два пункти, яких немає в офіційних доках і які є чисто його практикою: правило "не роби одразу, запиши в TODO для наступного агента" і щотижнева ручна чистка пам'яті. Обидва розумні і нижче включені в промпти.

## Етап 0: середовище

Мета етапу: агент може працювати годинами без вашого комп'ютера і без ручного підтвердження кожної команди.

**Підписка і моделі.** Для нон-стоп роботи потрібен Max (5x або 20x). Alex T каже, що Max 20x у нього вигорає за 2-3 дні активної розробки, тому дешевші плани для цього режиму не підходять. Opus для планування, архітектури і рев'ю; Sonnet для простих веб-проєктів і сабагентів-виконавців. Переходьте на нову модель одразу після релізу.

**Машина.** Окремий міні-ПК або Linux-сервер (у Red Carlos він уже є), 32 GB RAM, Docker. Claude Code працює через вашу підписку (вхід через `claude setup-token`), а не через API. Один застережний момент: Anthropic не дозволяє ділити одну підписку між кількома людьми або віддавати її автоматизованому "ферм-серверу"; один розробник на одну підписку, навіть якщо сесія крутиться на сервері.

**Мінімальна структура репозиторію на старті:**

```markdown
CLAUDE.md              # 20-40 рядків: стек, команди build/test/lint, правила, яких без цього не дотримаються
docs/
  ARCHITECTURE.md      # відповіді з інтерв'ю (етап 1)
  STAGES.md            # стейджі з критеріями готовності (етап 2)
  TODO.md              # черга задач для наступного агента (етап 4)
  DECISIONS.md         # коротко: що вирішили і чому
.claude/
  agents/              # визначення сабагентів (етап 3)
  settings.json        # дозволи, hooks
.worktreeinclude       # .env та інші gitignored-файли, які треба копіювати у worktree
.gitignore             # + .claude/worktrees/
```

**Шаблон CLAUDE.md** (короткий; усе, що потрібне лише іноді, йде у skills або docs/):

```markdown
# Project: <name>

## Stack
Next.js 15 (app router), Nest.js API, PostgreSQL 16 via Prisma, Docker Compose for local.

## Commands
- install: pnpm install
- dev: docker compose up -d && pnpm dev
- test: pnpm test (must pass before any commit)
- lint: pnpm lint && pnpm typecheck

## Rules
- Read docs/ARCHITECTURE.md and docs/STAGES.md before starting any task.
- Work only on the current stage in docs/STAGES.md. Do not start the next stage.
- Any idea, refactor or bug outside the current task: append it to docs/TODO.md, do not do it now.
- Every change must have a test. Run the full test suite before commit.
- Commit small and often with conventional commit messages.
- Never edit .env or secrets. Never run destructive git commands.
- When a stage is done: update docs/STAGES.md status, write a 5-line summary to docs/DECISIONS.md.
```

**Дозволи.** Щоб агент не зупинявся на кожному підтвердженні, налаштуйте allowlist у `.claude/settings.json` (pnpm, git commit, docker compose, тести) або запускайте на ізольованій машині з `--dangerously-skip-permissions`. Друге прийнятно лише на окремому міні-ПК або в контейнері без доступу до продакшн-секретів.

## Етап 1: інтерв'ю і spec

На цьому етапі вирішується 80% успіху: ви не передаєте задачу клієнта в Claude, а змушуєте Claude допитати вас, а потім записуєте результат у файл. Працюйте в plan mode (Shift+Tab двічі або `claude --permission-mode plan`), на Opus. Промпти англійською: так стабільніше спрацьовують інструменти і файли читаються всіма агентами однаково; відповідати можна українською.

**Промпт 1.1: інтерв'ю (версія "50 питань")**

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

**Промпт 1.2: запис відповідей у spec** (та сама сесія, після INTERVIEW COMPLETE)

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

**Промпт 1.3: коротка версія для малих проєктів** (лендінг, невеликий сайт, одна фіча)

```markdown
/plan
Here is the task: <task>. Interview me with AskUserQuestion, 10-15 questions max,
then write the plan to docs/ARCHITECTURE.md and wait for my approval before coding.
```

**Як це виглядає на практиці.** Інтерв'ю на 50 питань займає 30-60 хвилин, якщо ви знаєте проєкт. Якщо не знаєте домен, спочатку попросіть Claude пояснити вам предметну область і типові рішення (режим розмови, про який говорить Alex T), і лише потім запускайте інтерв'ю. Після запису spec зробіть `/clear`: реалізація має стартувати в чистому контексті і читати файл, а не пам'ятати розмову.

## Етап 2: розбиття на стейджі

Стейдж це одиниця контексту, а не одиниця часу: кожен стейдж має вміщатися в одну сесію агента без компакції і закінчуватися перевіркою, яку можна запустити командою. Саме це Alex T називає "спілкуватися з ним як з менеджером".

**Промпт 2.1: стейджі** (нова сесія після /clear, plan mode, Opus)

```markdown
Read docs/ARCHITECTURE.md and docs/DECISIONS.md.

You are the engineering manager for this project. Split the implementation into
6-12 stages and write them to docs/STAGES.md. Constraints:

- A stage must be completable by one agent in one session without running out of
  context: roughly 5-15 files touched. If bigger, split it.
- Stages must be ordered so that each one leaves the repo in a working, tested state.
- Stage 1 is always: repo skeleton, Docker, CI, test runner, lint, one trivial
  end-to-end test that passes. Nothing else.
- Mark which stages are independent of each other (can run in parallel) and which
  depend on a previous stage.
- For every stage write:
  - Goal (1 line)
  - Files/modules it creates or changes
  - Definition of done: a concrete, runnable check (test command, curl, screenshot)
  - Status: TODO
- Before writing the file, tell me where you expect the agent to struggle or get
  confused, and what extra context or rule would prevent it. Put those rules into
  the relevant stage.

Do not start implementing.
```

**Що перевірити в отриманому STAGES.md** (це єдине місце, де людський досвід дає найбільше):

- Definition of done кожного стейджу це команда, а не фраза "працює коректно".
- Немає стейджу "зробити весь бекенд": це ознака, що треба ділити далі.
- Паралельні стейджі не торкаються одних і тих самих файлів (інакше мерж-конфлікти на етапі 3).
- Спільні контракти (схема БД, типи API, спільні пакети) винесені в окремий ранній стейдж, щоб паралельні агенти будували на одному фундаменті.

**Промпт 2.2: виконання одного стейджу вручну** (базовий режим, коли ви ще не довіряєте автономії)

```markdown
Read CLAUDE.md, docs/ARCHITECTURE.md and docs/STAGES.md.
Implement Stage N only. When its definition of done passes, update its status to DONE
in docs/STAGES.md, commit, and stop. Anything you noticed outside Stage N goes into
docs/TODO.md, not into code.
```

Після кожного стейджу: `/clear`, нова сесія, наступний N. Агент читає стан з файлів, тому розмова не має значення і контекст не накопичується.

## Етап 3: тімлід, сабагенти, worktrees

Паралелізм прискорює лише незалежні стейджі; для залежних він лише палить токени і створює конфлікти (приклад Alex T з 40 репортами, які вперлися в одну базу). Є три офіційні механізми, від простого до складного.

| Механізм | Що це | Коли брати |
| --- | --- | --- |
| Сабагенти в одній сесії | Головна сесія запускає дочірні з власним контекстом; вони повертають резюме. Без isolation всі пишуть у ту саму папку | Стандартний варіант для 2-5 паралельних стейджів |
| Сабагенти + `isolation: worktree` | Кожен сабагент отримує свій git worktree і бранч `worktree-<name>`; Claude Code блокує запис у головний checkout | Коли агенти правлять файли (саме це описує Alex T) |
| `/batch` | Розбиває одну велику зміну на 5-30 сабагентів, кожен у worktree, кожен відкриває PR | Механічні міграції: 40 репортів, рефактор по всіх модулях |
| Agent Teams | Кілька повноцінних сесій, спільна черга задач, обмін повідомленнями, тімлід. Experimental, вимкнено за замовчуванням | Коли сабагентам треба спілкуватися між собою, а не лише з лідом |

**Підготовка (один раз на репозиторій):**

1. `echo ".claude/worktrees/" >> .gitignore`
2. Створіть `.worktreeinclude` з `.env`, `.env.local` та іншими gitignored-файлами, без яких проєкт не підніметься.
3. У `.claude/settings.json` додайте `"worktree": {"baseRef": "head"}`, якщо агенти мають будувати на незапушеній роботі, а не на main.
4. Переконайтеся, що стейдж зі спільними контрактами (схема, типи) вже змержений.

**Визначення сабагента-виконавця** `.claude/agents/stage-worker.md` (один універсальний замість окремих "фронтендер" і "бекендер": спеціалізація йде через стейдж, а не через роль):

```markdown
---
name: stage-worker
description: Implements exactly one stage from docs/STAGES.md in an isolated worktree, with tests, and reports back. Use for any implementation stage.
model: sonnet
isolation: worktree
---

You implement one stage of this project. You will be told the stage number.

Procedure:
1. Read CLAUDE.md, docs/ARCHITECTURE.md, docs/DECISIONS.md and your stage in docs/STAGES.md.
2. Install dependencies in this worktree if needed. Make sure tests run before you change anything.
3. Implement the stage. Write tests alongside the code.
4. Run lint, typecheck and the full test suite. Fix until green.
5. Run the stage's definition-of-done check from STAGES.md. If it fails, fix and repeat.
6. Commit with a conventional message. Do not merge, do not touch other stages.
7. Anything you noticed outside your stage: append to docs/TODO.md as one line each.

Report back in under 15 lines: what you built, the commands you ran and their results,
the branch name, and any blockers. Do not paste code into the report.
```

**Визначення рев'юера** `.claude/agents/stage-reviewer.md` (офіційний патерн Writer/Reviewer: свіжий контекст не захищає свій код):

```markdown
---
name: stage-reviewer
description: Reviews a stage branch against docs/STAGES.md and ARCHITECTURE.md before merge. Read-only. Use after every stage-worker.
model: opus
tools: Read, Grep, Glob, Bash
---

You review a branch produced by another agent. You did not write this code; be critical.
Check, in order: does it satisfy the stage's definition of done; does it follow ARCHITECTURE.md
and DECISIONS.md; are there tests and do they test behaviour, not implementation; security
(input validation, auth, secrets); anything touched outside the stage's scope.
Run the tests yourself. Output: APPROVE or REQUEST CHANGES, then a numbered list of
concrete issues with file:line. Max 20 lines.
```

**Промпт 3.1: тімлід** (головна сесія, Opus; це версія "ти тімлід, створи 5 сабагентів" з дзвінка)

```markdown
You are the tech lead. You do not write application code yourself; you delegate,
review and merge. Read docs/STAGES.md.

For every stage with status TODO whose dependencies are DONE:
- launch a stage-worker subagent for it, in parallel with the other independent stages
  (max 4 at once), using worktrees for your agents.
- when a worker reports back, launch stage-reviewer on its branch.
- on APPROVE: merge the branch into the current branch, run the full test suite on the
  merged result, mark the stage DONE in docs/STAGES.md, delete the worktree.
- on REQUEST CHANGES: send the review back to a new stage-worker with the branch name
  and the list of issues. Max 2 review rounds per stage; after that stop and ask me.
- on merge conflict: resolve it yourself if trivial, otherwise stop and ask me.

Repeat until no stage can be started. Then give me a status table: stage, status,
branch, test result, open issues. Keep your own context small: do not read the
workers' diffs, read only their reports and the reviewer's verdicts.
```

Зауваження про ліміт паралелізму. Alex T згадує 10 сабагентів; Сергій бачив стелю біля 3. Реальний обмежувач не інструмент, а rate limit підписки та RAM машини: кожен worktree з Docker і node\_modules це окремий набір процесів. Почніть з 3-4, піднімайте, коли бачите, що стабільно.

## Етап 4: автономна робота нон-стоп

Агент зупиняється з двох причин: він вважає, що закінчив, або йому потрібна ваша відповідь. Обидві лікуються не проханням "не зупиняйся", а перевіркою, яку він має пройти, і правилом, що рішення ухвалює він сам і фіксує їх у файлі.

**Три способи зробити це, від простого до надійного:**

| Спосіб | Як | Плюси / мінуси |
| --- | --- | --- |
| Промпт тімліду з правилом "вирішуй сам" | Промпт 4.1 нижче | Нуль налаштувань; агент все одно може зупинитись через кілька годин |
| `/goal` або Stop hook | Задаєте умову завершення (всі стейджі DONE і тести зелені); спроба зупинитись без виконання умови повертає агента в роботу | Офіційний механізм; працює в межах одного контексту, тобто контекст забивається |
| Ralph loop | Зовнішній цикл запускає свіжу сесію `claude -p` з тим самим промптом, поки умова не виконана. Стан живе в файлах і git, а не в контексті | Найближче до "30-40 годин нон-стоп"; потрібен ліміт ітерацій, інакше спалить підписку на циклічній помилці |

**Промпт 4.1: додаток до промпту тімліда для роботи без людини**

```markdown
I will be away for the next 8 hours. Do not stop to ask me questions.
When you face a decision:
- if ARCHITECTURE.md or DECISIONS.md answers it, follow them;
- otherwise pick the simplest option that keeps tests green, and append one line to
  docs/DECISIONS.md: "[AUTO] <decision>: <reason>". I will review these in the morning;
- only if the decision is irreversible (deleting data, changing a public API contract,
  paying for a service) write it to docs/TODO.md under "## Needs human" and move to
  another stage instead.
If a stage fails its definition of done 3 times in a row, mark it BLOCKED in STAGES.md
with the error, and continue with other stages.
You are done only when every stage is DONE or BLOCKED and `pnpm test` passes on the
merged branch. Then write docs/NIGHT-REPORT.md: what was done, what is blocked, what
needs me.
```

**Правило TODO.md** (його трик "не роби одразу, запиши для наступного агента"; вже є в шаблоні CLAUDE.md вище). Чому це працює: агент, який посеред стейджу побачив "о, тут би рефакторнути", засмічує контекст і розширює diff. Запис у файл коштує один рядок, а свіжий агент потім робить це з чистим контекстом. Формат:

```markdown
# TODO
## Needs human
- [ ] ...
## Next agent
- [ ] (stage 4) extract PriceCalculator into shared package, used by 3 modules
- [ ] (stage 6) add index on orders.customer_id, query is slow in tests
```

**Ralph loop мінімально** (запускати на окремій машині через tmux або systemd):

```markdown
#!/usr/bin/env bash
# ralph.sh: fresh session per iteration, state lives in files + git
set -e
MAX=${MAX:-30}
for i in $(seq 1 $MAX); do
  echo "=== iteration $i ==="
  claude -p "$(cat docs/LOOP-PROMPT.md)" --permission-mode acceptEdits --max-turns 200 || true
  if grep -q 'ALL_STAGES_DONE' docs/STAGES.md; then echo done; exit 0; fi
  sleep 30
done
```

`docs/LOOP-PROMPT.md` це промпт 3.1 плюс 4.1 плюс рядок: "When every stage is DONE and tests pass, add the line ALL\_STAGES\_DONE to the top of docs/STAGES.md." Офіційний плагін робить те саме через Stop hook без bash: `/plugin install ralph-wiggum@claude-plugins-official`, потім `/ralph-loop "<prompt>" --max-iterations 30 --completion-promise "ALL_STAGES_DONE"`. Завжди ставте `--max-iterations`.

**Верифікація замість рев'ю коду.** Alex T не читає код, але це працює лише тому, що агент має чим довести результат. Мінімум для веб-проєкту: unit-тести, один e2e-прогін через Playwright (наявний у Claude Code середовищі), скріншоти ключових екранів у `docs/screens/` після кожного стейджу. Вранці ви дивитесь NIGHT-REPORT.md, скріншоти і клацаєте staging, а не читаєте diff.

## Етап 5: щотижнева гігієна контексту

Раз на тиждень (або після кожних 2-3 нічних прогонів) 1-2 години на чистку: файли, які агенти читають на старті, роздуваються самі собою, і кожен зайвий рядок там коштує токенів у кожній сесії кожного агента.

Чек-лист:

- [ ] CLAUDE.md: для кожного рядка питання "якщо прибрати, агент помилиться?" Ні = видалити або перенести в docs/ чи skill.
- [ ] Правила, які агенти дописали самі (в CLAUDE.md, DECISIONS.md, memory): залишити лише ті, з якими ви згодні.
- [ ] TODO.md: викинути застаріле, згрупувати решту в нові стейджі в STAGES.md.
- [ ] DECISIONS.md: рядки \[AUTO\] переглянути; неправильні рішення перетворити на стейдж "переробити X".
- [ ] ARCHITECTURE.md: чи відповідає реальному коду; розбіжності виправити в документі, а не в коді (якщо код кращий).
- [ ] `git worktree list` і `git branch`: залишки видалити.
- [ ] Розмір сумарного стартового контексту (CLAUDE.md + файли, які він наказує читати) не більше 20-30k токенів; перевірити через `/context`.

**Промпт 5.1: чистка за допомогою самого Claude** (свіжа сесія, Opus)

```markdown
Read CLAUDE.md, docs/ARCHITECTURE.md, docs/DECISIONS.md, docs/TODO.md, docs/STAGES.md.
Act as a skeptical editor. For each file propose cuts and merges:
- CLAUDE.md: keep only rules whose removal would cause a concrete mistake. Everything
  else moves to docs/ or is deleted. Target under 40 lines.
- DECISIONS.md: group [AUTO] lines, flag the ones that contradict ARCHITECTURE.md.
- TODO.md: remove items already done (check the code), group the rest into proposed
  new stages with a definition of done each.
- STAGES.md: remove DONE stages into docs/STAGES-ARCHIVE.md, keep the file short.
Show me the diff as a plan first. Do not apply until I approve.
```

## Прийом клієнтського фідбеку

Найдорожча частина після першої збірки, за словами Alex T, це не код, а прохід по інтерфейсу з помітками "тут не так". Цю роботу можна віддати клієнту і агенту.

1. Клієнт записує екран з голосом (Loom, QuickTime), клацаючи staging і коментуючи.
2. Ви перетворюєте відео на транскрипт плюс кадри (ffmpeg кожні 2-3 секунди або на зміну сцени; whisper для аудіо). Claude не дивиться відео як відео, він читає текст і послідовні скріншоти.
3. Промпт 6.1 перетворює це на стейджі.

**Промпт 6.1: фідбек у стейджі**

```markdown
In feedback/2026-11-10/ there is transcript.txt and frames/*.png from the client's
screen recording (timestamps in file names). Read the transcript, look at the frames
next to each complaint, and map every remark to a screen and component in our code.
Produce docs/FEEDBACK-2026-11-10.md: a table with columns remark, screen, file(s),
severity (bug / UX / wish), proposed fix in one line. Then append the bugs and UX
items as new stages to docs/STAGES.md with a definition of done each. Wishes go to
docs/TODO.md. Do not implement anything yet.
```

Для регулярного самотестування без клієнта у Red Carlos вже є qa-agents (qa-lead, qa-web з Claude in Chrome, qa-api): це саме той "агент, який лазить по сайту і кидає репорти", про який говорить Alex T. Їх можна підключити як перевірку після кожного нічного прогону.

## Критичний погляд

Механіка (етапи 0-5) підтверджена офіційними доками і незалежними звітами; висновки про людей і строки це особистий досвід однієї людини в специфічних умовах.

| Твердження | Оцінка | Коментар |
| --- | --- | --- |
| Інтерв'ю + spec у файл, стейджі, сабагенти, worktrees, короткий CLAUDE.md | Підтверджено | Дослівно в Best practices Anthropic |
| 30-40 годин нон-стоп | Реально, але з застереженням | Працює через зовнішній цикл (Ralph), а не одну сесію; п'ятигодинні вікна лімітів підписки будуть зупиняти прогін, цикл має це перечікувати |
| Будь-який проєкт за 3 дні розробки + дебаг | Спірно | У нього внутрішні продукти без зовнішнього замовника: немає погодження дизайну, зміни скоупу, чужого legacy. Для студії з клієнтами термін диктує комунікація, а не код |
| Код не читаю, крім military | Ризиковано для клієнтської роботи | Клієнт отримує код і підтримує його роками; відповідальність за безпеку і персональні дані на вас. Заміна ручному рев'ю це не "не читати", а reviewer-агент + тести + вибіркове читання auth, платежів, міграцій |
| Людський процес dev > review > QA не має сенсу | Наполовину | Процес потрібен, але всередині однієї голови і одного репо, а не через Telegram. Саме передача контексту між людьми вбиває швидкість, що Сергій сам назвав на дзвінку |
| Мідли і джуни мертва професія, звільняти | Думка, не факт | Практичний висновок скромніший: одиниця роботи стає "проєкт або епік на людину", а не "таск на людину". Хто може вести проєкт цілісно, той і працює в цьому режимі |
| Сервер не можна, бо забанять; міні-ПК можна | Неточно | Правило стосується не заліза, а спільного використання однієї підписки кількома людьми. Один розробник, одна підписка, його сесія на сервері це нормально |

Ризики специфічно для студії з клієнтами: код клієнта і секрети на машині з `--dangerously-skip-permissions` (тримати лише staging-секрети); витрати на підписки, які треба закласти в ціну проєкту; договірні обмеження деяких клієнтів на використання AI.

## Як це накласти на Red Carlos

Найбільший виграш не в промптах, а в зміні одиниці роботи: одна людина веде проєкт від інтерв'ю до здачі, а не роздає таски через Telegram. Сергій на дзвінку сам дійшов до цього висновку.

**Пілот: один проєкт, одна людина, цей гайд як є.** Брати greenfield з зрозумілим скоупом (лендінг + адмінка, невеликий SaaS, внутрішній інструмент), не brownfield WordPress і не military-рівень відповідальності. Критерії успіху зафіксувати до старту: календарний час до staging, години людини, витрачені ліміти підписки, кількість багів від QA на першому прогоні.

**Що вже є і куди вбудовується:**

| Є | Роль у цьому процесі |
| --- | --- |
| qa-agents (qa-lead на Opus, qa-web/qa-api на Sonnet, checkpoint для оператора) | Перевірка після нічного прогону і перед демо клієнту; та сама архітектура lead + specialists, що й у промпті 3.1 |
| Власний Linux-сервер | Машина для нічних прогонів замість міні-ПК; одна підписка на одного розробника |
| Стейджевий формат ТЗ (без тижнів і дедлайнів) | STAGES.md це той самий формат, тільки для агента, а не для падавана |
| Ручний QA | Залишається для "тупіння в контексті бізнесу", як і каже Alex T; регрес і клікання йдуть агентам |

**Наступні кроки:**

- [ ] Вибрати пілотний проєкт і власника (одна людина на проєкт).
- [ ] Скласти шаблонний репозиторій Red Carlos: CLAUDE.md, docs/, .claude/agents/ з stage-worker і stage-reviewer, .worktreeinclude, settings.json з allowlist.
- [ ] Запустити етапи 1-2 разом з Alex T на 15-хвилинних дзвінках, як він запропонував.
- [ ] Перший нічний прогін лише на незалежних стейджах, з `--max-iterations 10`, на сервері без продакшн-секретів.
- [ ] Після пілоту: ретро по критеріях вище, потім рішення про структуру команди, а не навпаки.

## Джерела

- [Best practices for Claude Code](https://code.claude.com/docs/en/best-practices) (Anthropic): контекст, CLAUDE.md, plan mode, interview-to-spec, subagents, Writer/Reviewer, /batch, headless
- [Run parallel sessions with worktrees](https://code.claude.com/docs/en/worktrees.md) (Anthropic): --worktree, isolation: worktree, .worktreeinclude, cleanup
- [Subagents](https://code.claude.com/docs/en/sub-agents) і [Agent teams](https://code.claude.com/docs/en/agent-teams) (Anthropic)
- [Ralph Wiggum as a software engineer](https://ghuntley.com/ralph/) (Geoffrey Huntley): першоджерело патерну нон-стоп циклу
- [The Ralph Wiggum technique](https://www.atcyrus.com/stories/ralph-wiggum-technique-claude-code-autonomous-loops): офіційний плагін і Stop hook
- [Stop prompting Claude Code, let it interview you](https://velvetshark.com/stop-prompting-claude-code-let-it-interview-you): приклад інтерв'ю-команди з AskUserQuestion
- [How to use git worktrees with Claude Code](https://crystl.dev/blog/git-worktrees-claude-code/): чому сабагенти без isolation пишуть у спільну папку
- Транскрипт дзвінка "Розробка з ШІ за 2 тижні", 3 листопада 2026 (Alex T, Сергій Мороз, Михайло Пиріг)
