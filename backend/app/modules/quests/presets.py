"""Quest presets: the built-in library (static, localized), user-saved templates and the gold
estimate shown while a quest is created.

Built-ins are data, not rows. Saved templates live in ``saved_quest_template`` and every query
here is scoped to the caller (``owner_id``); another user's id is simply not found.
"""

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.common.enums import (
    Attribute,
    ConfirmationMode,
    Difficulty,
    Locale,
    Recurrence,
)
from app.modules.common.validation import Description, Title
from app.modules.quests.models import SavedQuestTemplate
from app.modules.quests.schemas import Gold
from app.modules.users.models import User

#: Saved templates one user may keep.
MAX_SAVED = 50
#: Days in a "month" for the estimate (the brief's example: 50 Gold a day is about 1,500).
DAYS_PER_MONTH = 30
WEEKS_PER_MONTH = 4


@dataclass(frozen=True)
class Builtin:
    key: str
    attribute: Attribute
    difficulty: Difficulty
    gold: int
    recurrence: Recurrence
    en: str
    uk: str


A, D, R = Attribute, Difficulty, Recurrence
BUILTINS: tuple[Builtin, ...] = (
    Builtin("run", A.PHYSICAL, D.NORMAL, 50, R.ONCE, "Go for a run", "Піти на пробіжку"),
    Builtin("workout", A.PHYSICAL, D.NORMAL, 40, R.DAILY, "Do a workout", "Зробити тренування"),
    Builtin("steps", A.PHYSICAL, D.EASY, 20, R.DAILY, "Walk 8,000 steps", "Пройти 8000 кроків"),
    Builtin(
        "stretch", A.PHYSICAL, D.EASY, 15, R.DAILY, "Stretch for 10 minutes", "Розтяжка 10 хвилин"
    ),
    Builtin("read", A.INTELLECTUAL, D.EASY, 20, R.DAILY, "Read for 30 minutes", "Читати 30 хвилин"),
    Builtin(
        "course",
        A.INTELLECTUAL,
        D.NORMAL,
        60,
        R.WEEKLY,
        "Finish a course lesson",
        "Пройти урок курсу",
    ),
    Builtin("language", A.INTELLECTUAL, D.EASY, 20, R.DAILY, "Practise a language", "Вивчати мову"),
    Builtin(
        "summary",
        A.INTELLECTUAL,
        D.NORMAL,
        35,
        R.ONCE,
        "Write a book summary",
        "Написати конспект книги",
    ),
    Builtin(
        "plan", A.DISCIPLINE, D.EASY, 20, R.DAILY, "Plan tomorrow", "Спланувати завтрашній день"
    ),
    Builtin("early", A.DISCIPLINE, D.NORMAL, 40, R.DAILY, "Get up on time", "Прокинутися вчасно"),
    Builtin("clean", A.DISCIPLINE, D.NORMAL, 50, R.WEEKLY, "Clean the home", "Прибрати вдома"),
    Builtin(
        "budget", A.DISCIPLINE, D.HARD, 80, R.WEEKLY, "Review the budget", "Переглянути бюджет"
    ),
    Builtin(
        "call",
        A.SOCIAL,
        D.EASY,
        25,
        R.WEEKLY,
        "Call a friend or family",
        "Подзвонити другу чи рідним",
    ),
    Builtin("meet", A.SOCIAL, D.NORMAL, 60, R.ONCE, "Meet someone new", "Познайомитися з кимось"),
    Builtin("help", A.SOCIAL, D.NORMAL, 40, R.ONCE, "Help someone out", "Допомогти комусь"),
    Builtin("date", A.SOCIAL, D.HARD, 90, R.WEEKLY, "Plan a date night", "Спланувати побачення"),
    Builtin(
        "draw", A.CREATIVITY, D.NORMAL, 40, R.ONCE, "Draw or paint something", "Намалювати щось"
    ),
    Builtin("write", A.CREATIVITY, D.EASY, 20, R.DAILY, "Write a page", "Написати сторінку"),
    Builtin(
        "music",
        A.CREATIVITY,
        D.NORMAL,
        40,
        R.DAILY,
        "Practise an instrument",
        "Пограти на інструменті",
    ),
    Builtin(
        "cook", A.CREATIVITY, D.HARD, 70, R.ONCE, "Cook a new recipe", "Приготувати новий рецепт"
    ),
    Builtin("sleep", A.WELLBEING, D.NORMAL, 40, R.DAILY, "Sleep 8 hours", "Спати 8 годин"),
    Builtin(
        "meditate",
        A.WELLBEING,
        D.EASY,
        20,
        R.DAILY,
        "Meditate for 10 minutes",
        "Медитувати 10 хвилин",
    ),
    Builtin("water", A.WELLBEING, D.EASY, 15, R.DAILY, "Drink enough water", "Пити достатньо води"),
    Builtin(
        "detox", A.WELLBEING, D.HARD, 75, R.WEEKLY, "A screen-free evening", "Вечір без екранів"
    ),
)


class PresetOut(BaseModel):
    """One preset. ``saved_id`` is set only for the caller's own saved templates (the id that
    ``DELETE /quest-presets/{id}`` takes); built-ins have ``builtin=True`` and a stable ``key``."""

    key: str
    builtin: bool
    saved_id: int | None
    title: str
    description: str | None
    attribute: Attribute
    difficulty: Difficulty
    gold: int
    recurrence: Recurrence
    confirmation: ConfirmationMode
    photo_required: bool


class PresetCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: Title
    description: Description = None
    attribute: Attribute
    difficulty: Difficulty = Difficulty.NORMAL
    gold: Gold
    recurrence: Recurrence = Recurrence.ONCE
    confirmation: ConfirmationMode = ConfirmationMode.MANUAL
    photo_required: bool = False


class PresetList(BaseModel):
    builtin: list[PresetOut]
    saved: list[PresetOut]


class Estimate(BaseModel):
    """Most Gold the quest can mint if every day / week is completed."""

    gold: int
    recurrence: Recurrence
    weekly: int
    monthly: int


class TooManySavedError(Exception):
    pass


class PresetNotFoundError(Exception):
    pass


def builtin_presets(locale: Locale) -> list[PresetOut]:
    return [
        PresetOut(
            key=b.key,
            builtin=True,
            saved_id=None,
            title=b.uk if locale == Locale.UK else b.en,
            description=None,
            attribute=b.attribute,
            difficulty=b.difficulty,
            gold=b.gold,
            recurrence=b.recurrence,
            confirmation=ConfirmationMode.MANUAL,
            photo_required=False,
        )
        for b in BUILTINS
    ]


def _saved_out(row: SavedQuestTemplate) -> PresetOut:
    return PresetOut(
        key=f"saved-{row.id}",
        builtin=False,
        saved_id=row.id,
        title=row.title,
        description=row.description,
        attribute=row.attribute,
        difficulty=row.difficulty,
        gold=row.gold,
        recurrence=row.recurrence,
        confirmation=row.confirmation,
        photo_required=row.photo_required,
    )


def estimate(gold: int, recurrence: Recurrence) -> Estimate:
    match recurrence:
        case Recurrence.DAILY:
            weekly, monthly = gold * 7, gold * DAYS_PER_MONTH
        case Recurrence.WEEKLY:
            weekly, monthly = gold, gold * WEEKS_PER_MONTH
        case _:
            weekly = monthly = gold
    return Estimate(gold=gold, recurrence=recurrence, weekly=weekly, monthly=monthly)


async def list_presets(session: AsyncSession, user: User) -> PresetList:
    rows = await session.scalars(
        select(SavedQuestTemplate)
        .where(SavedQuestTemplate.owner_id == user.id)
        .order_by(SavedQuestTemplate.id)
    )
    return PresetList(builtin=builtin_presets(user.locale), saved=[_saved_out(r) for r in rows])


async def save_preset(session: AsyncSession, user: User, body: PresetCreate) -> PresetOut:
    count = await session.scalar(
        select(func.count())
        .select_from(SavedQuestTemplate)
        .where(SavedQuestTemplate.owner_id == user.id)
    )
    if (count or 0) >= MAX_SAVED:
        raise TooManySavedError
    row = SavedQuestTemplate(owner_id=user.id, **body.model_dump())
    session.add(row)
    await session.commit()
    return _saved_out(row)


async def delete_preset(session: AsyncSession, user: User, preset_id: int) -> None:
    result = await session.execute(
        delete(SavedQuestTemplate)
        .where(SavedQuestTemplate.id == preset_id, SavedQuestTemplate.owner_id == user.id)
        .returning(SavedQuestTemplate.id)
    )
    if result.scalar_one_or_none() is None:
        await session.rollback()
        raise PresetNotFoundError
    await session.commit()
