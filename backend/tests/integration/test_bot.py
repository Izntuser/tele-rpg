"""The bot: the webhook route, /start with deep-link payloads, polling and webhook setup.
Updates are fed through the real aiogram dispatcher; FakeBot records the replies."""

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from aiogram.methods import SendMessage, SetWebhook
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import polling
from app.bot.dispatcher import (
    get_bot,
    set_bot,
    setup_webhook,
    startapp_url,
    uses_fake_bot,
    valid_start_param,
)
from app.bot.fake import FakeBot
from app.bot.handlers.start import live_user
from app.core import clock
from app.core.config import Settings, get_settings
from app.modules.common.enums import Locale
from tests import factories

SECRET = "s" * 40
BASE_URL = "https://telerpg.example.com"


@pytest.fixture
def bot() -> Iterator[FakeBot]:
    fake = FakeBot()
    set_bot(fake)
    try:
        yield fake
    finally:
        set_bot(None)


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    settings = get_settings()
    monkeypatch.setattr(settings, "tg_webhook_secret", SecretStr(SECRET))
    monkeypatch.setattr(settings, "tg_bot_username", "telerpg_bot")
    monkeypatch.setattr(settings, "tg_app_short_name", "play")
    monkeypatch.setattr(settings, "public_base_url", BASE_URL)
    return settings


_update_id = 0


def start_update(
    text: str = "/start", *, tg_id: int = 555_000_001, language_code: str | None = "en"
) -> dict[str, Any]:
    global _update_id
    _update_id += 1
    sender: dict[str, Any] = {"id": tg_id, "is_bot": False, "first_name": "Alice"}
    if language_code is not None:
        sender["language_code"] = language_code
    command = text.split(" ", 1)[0]
    return {
        "update_id": _update_id,
        "message": {
            "message_id": _update_id,
            "date": 1_768_478_400,
            "chat": {"id": tg_id, "type": "private"},
            "from": sender,
            "text": text,
            "entities": (
                [{"type": "bot_command", "offset": 0, "length": len(command)}]
                if text.startswith("/")
                else []
            ),
        },
    }


async def feed(client: httpx.AsyncClient, update: dict[str, Any]) -> httpx.Response:
    return await client.post(f"/tg/webhook/{SECRET}", json=update)


def button(message: SendMessage) -> Any:
    markup: Any = message.reply_markup
    [[only]] = markup.inline_keyboard
    return only


async def test_wrong_or_missing_secret_is_404(
    client: httpx.AsyncClient, bot: FakeBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert (await client.post("/tg/webhook/nope", json=start_update())).status_code == 404
    assert (await client.post(f"/tg/webhook/{SECRET}x", json=start_update())).status_code == 404
    assert (await client.post("/tg/webhook/", json=start_update())).status_code == 404
    monkeypatch.setattr(get_settings(), "tg_webhook_secret", SecretStr(""))
    assert (await client.post(f"/tg/webhook/{SECRET}", json=start_update())).status_code == 404
    assert bot.calls == []


async def test_webhook_is_not_under_api_and_not_in_openapi(client: httpx.AsyncClient) -> None:
    schema = (await client.get("/openapi.json")).json()
    assert not any(path.startswith("/tg") for path in schema["paths"])
    assert (await client.post(f"/api/tg/webhook/{SECRET}", json={})).status_code == 404


async def test_start_replies_with_a_welcome_and_a_web_app_button(
    client: httpx.AsyncClient, bot: FakeBot
) -> None:
    response = await feed(client, start_update())
    assert response.status_code == 200 and response.json() == {"ok": True}
    [message] = bot.messages
    assert message.chat_id == 555_000_001
    assert message.text is not None and message.text.startswith("Welcome to Modern Life RPG!")
    only = button(message)
    assert only.text == "Open the app"
    assert only.web_app is not None and only.web_app.url == BASE_URL


@pytest.mark.parametrize(
    ("payload", "text"),
    [
        ("invite_" + "Ab-_9" * 8 + "xyz", "You have been invited to an adventure."),
        ("q_42", "Open the app to see this quest."),
    ],
)
async def test_start_payload_is_passed_through_to_startapp(
    client: httpx.AsyncClient, bot: FakeBot, payload: str, text: str
) -> None:
    await feed(client, start_update(f"/start {payload}"))
    [message] = bot.messages
    assert message.text is not None and message.text.startswith(text)
    assert button(message).url == f"https://t.me/telerpg_bot/play?startapp={payload}"


@pytest.mark.parametrize("payload", ["../etc", "q_" + "1" * 70, "hack_1", "q_a b"])
async def test_unknown_or_malformed_payloads_are_dropped(
    client: httpx.AsyncClient, bot: FakeBot, payload: str
) -> None:
    await feed(client, start_update(f"/start {payload}"))
    [message] = bot.messages
    only = button(message)
    assert only.url is None and only.web_app is not None
    assert message.text is not None and message.text.startswith("Welcome")


async def test_without_configured_names_the_payload_cannot_be_linked(
    client: httpx.AsyncClient, bot: FakeBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "tg_bot_username", "")
    await feed(client, start_update("/start q_42"))
    assert button(bot.messages[0]).web_app.url == BASE_URL


async def test_start_speaks_ukrainian_to_a_ukrainian_client(
    client: httpx.AsyncClient, bot: FakeBot
) -> None:
    await feed(client, start_update(language_code="uk"))
    [message] = bot.messages
    assert message.text is not None and message.text.startswith("Вітаємо в Modern Life RPG!")
    assert button(message).text == "Відкрити застосунок"


async def test_a_known_user_gets_their_own_locale_and_a_welcome_back(
    client: httpx.AsyncClient, session: AsyncSession, bot: FakeBot
) -> None:
    user = await factories.create_user(
        session, tg_user_id=555_000_777, locale=Locale.UK, onboarded_at=clock.now()
    )
    await session.commit()
    await feed(client, start_update(tg_id=user.tg_user_id, language_code="en"))
    [message] = bot.messages
    assert message.text == "З поверненням, шукачу пригод! Твої квести чекають."


async def test_deleted_accounts_never_match_a_telegram_id(
    client: httpx.AsyncClient, session: AsyncSession, bot: FakeBot
) -> None:
    gone = await factories.create_user(
        session, locale=Locale.UK, onboarded_at=clock.now(), deleted_at=clock.now()
    )
    original_tg_id = gone.tg_user_id
    gone.tg_user_id = -gone.id
    await session.commit()
    assert await live_user(session, -gone.id) is None
    assert await live_user(session, original_tg_id) is None
    await feed(client, start_update(tg_id=original_tg_id, language_code="en"))
    [message] = bot.messages
    # Treated as a newcomer in their client's language, not as the deleted account.
    assert message.text is not None and message.text.startswith("Welcome to Modern Life RPG!")


async def test_other_messages_and_bad_updates(client: httpx.AsyncClient, bot: FakeBot) -> None:
    assert (await feed(client, start_update("hello"))).status_code == 200
    assert bot.messages == []
    bad = await client.post(f"/tg/webhook/{SECRET}", content=b"{not json")
    assert bad.status_code == 400
    bad = await client.post(f"/tg/webhook/{SECRET}", json={"message": {}})
    assert bad.status_code == 400


async def test_a_failing_handler_still_acknowledges_the_update(
    client: httpx.AsyncClient, bot: FakeBot
) -> None:
    bot.fail_next(RuntimeError("telegram down"))
    response = await feed(client, start_update())
    assert response.status_code == 200  # Telegram must not redeliver it forever


def test_start_params_and_links() -> None:
    assert valid_start_param("q_12") == "q_12"
    assert valid_start_param("invite_abc-DEF_1") == "invite_abc-DEF_1"
    assert valid_start_param("q_") is None
    assert valid_start_param("x_1") is None
    assert valid_start_param(None) is None
    assert startapp_url("r_3") == "https://t.me/telerpg_bot/play?startapp=r_3"
    assert startapp_url(None) == "https://t.me/telerpg_bot/play"
    assert startapp_url("bad param") == "https://t.me/telerpg_bot/play"


async def test_setup_webhook_points_telegram_at_the_secret_route(bot: FakeBot) -> None:
    await setup_webhook(bot)
    [call] = bot.calls
    assert isinstance(call.method, SetWebhook)
    assert call.method.url == f"{BASE_URL}/tg/webhook/{SECRET}"


def test_fake_bot_outside_prod_and_for_the_dev_token() -> None:
    assert uses_fake_bot(get_settings())  # APP_ENV=test
    assert isinstance(get_bot(), FakeBot)
    set_bot(None)


async def test_polling_refuses_the_fake_token(bot: FakeBot) -> None:
    assert await polling.main() == 1
    assert bot.calls == []
