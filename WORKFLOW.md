# Флоу: що запускати і в якому порядку

За гайдом `guide/Метод_..._v2_1.md`. Кожен крок це окрема сесія `claude`, між кроками `/clear`.
Агенти цей файл не читають, він для людини.

## 0. Один раз (вже зроблено)
CLAUDE.md, AGENTS.md (симлінк), `.claude/settings.json`, `.claude/agents/*` (4 агенти),
`.claude/skills/*` (команди нижче), `scripts/*`, `ralph.sh`, `docs/LOOP-PROMPT.md`,
порожні PROGRESS / LEAD-LOG / TODO, git-репозиторій.

Необов'язково: Codex (`npm i -g @openai/codex && codex login --device-auth`,
`~/.codex/config.toml`: `approval_policy = "never"`, `sandbox_mode = "workspace-write"`).
Без Codex: `low`-стейджі йдуть на Sonnet (FALLBACK), а sensitive-стейджі рев'ює другий Opus-рев'юер.

## 1. Інтерв'ю і spec (Opus)
```
claude --permission-mode plan          # або Shift+Tab двічі
/interview <бриф або шлях до файлу з брифом>
   ... відповідаєш на 50+ питань ...    → INTERVIEW COMPLETE
Shift+Tab (вийти з plan mode)
/spec                                   → docs/ARCHITECTURE.md, DECISIONS.md, Stack у CLAUDE.md
```
Невелика задача: замість цих двох кроків `/interview-short <задача>`.
Прочитай ARCHITECTURE.md, поправ. `/clear`.

## 2. Стейджі (Opus)
```
/stages                                 → docs/stages.json + STAGES.md
```
Перевір за чеклістом, який він виведе (запусти 1-2 dod_command, вони мають ПАДАТИ). Потім:
```
git add -A && git commit -m "docs: spec and stages"
scripts/lock-stages.sh lock             # у своєму терміналі: забороняє агентам правити stages.json
```

## 3. Розробка вдень (головна сесія = тімлід, сама код не пише)
Два режими, обирай:
- `/next-stage` → один стейдж (воркер → рев'ю → мерж → `--mark`), потім `/clear` і знову. Почни так для S01-S02.
- `/lead` → цикл по всіх доступних стейджах, паралель до 4 worktree, якщо 3+ незалежних.

`/status` будь-коли: таблиця стейджів, хвіст LEAD-LOG, "Needs human".

## 4. Вночі / без людини
Найкраще (свіжа сесія на кожну ітерацію, переживає вичерпання контексту):
```
tmux new -s night
MAX=30 ./ralph.sh                       # лог у logs/ralph-*.log; Ctrl+b d щоб відключитись
```
Простіше, в одній сесії: `/autonomous 8`.
Вранці: `docs/NIGHT-REPORT.md`, `docs/LEAD-LOG.md`, `docs/screens/`, рядки `[AUTO]` у DECISIONS.md,
"Needs human" у TODO.md. Потім сам робиш `git push`: агентам пуш заборонено.
Розблокувати стейдж після розбору: `scripts/block-stage.sh S07 --clear`.

## 5. Раз на тиждень
`/hygiene` → план чистки (сам нічого не застосовує). Якщо чіпає stages.json, спершу
`scripts/lock-stages.sh unlock`, після правок `lock`.

## 6. Фідбек клієнта
Відео в `feedback/<дата>/` → кадри + транскрипт (команди підкаже скіл) →
`scripts/lock-stages.sh unlock` → `/feedback <дата>` → перевірити → `lock` → `/lead` або `ralph.sh`.

## Хто що робить
| Агент | Модель | Коли |
| --- | --- | --- |
| stage-worker | sonnet / opus (override від ліда) | medium, high, sensitive; fallback для codex |
| codex-worker | haiku-обгортка над Codex | low + normal |
| stage-reviewer | opus, read-only, свій worktree | після кожного воркера |
| codex-reviewer | haiku-обгортка над Codex | додатково для risk: sensitive |

## Якщо щось пішло не так
- Агент "не може" запустити команду → у headless дозволено лише те, що в `allow` у `.claude/settings.json`.
  Додай потрібну команду (наприклад, якщо стек не на pnpm). Перевірка: `/permissions`.
- Стейдж заблоковано двічі → розбий його на менші через `/hygiene`.
- Залишки worktree: `git worktree list`, `git worktree prune`.
