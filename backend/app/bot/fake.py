"""``FakeBot``: an aiogram ``Bot`` whose HTTP session records every API call and never touches
the network (ARCHITECTURE §8 "test": outbound Telegram calls go to FakeBot).

Used whenever ``APP_ENV=test`` or the token is the public fake dev token, and by every test.
``fail_next`` queues exceptions so tests can drive the dispatcher's retry paths.
"""

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import SendMessage, TelegramMethod
from aiogram.methods.base import TelegramType
from aiogram.types import Chat, Message, User

from app.core.config import DEV_TG_BOT_TOKEN

FAKE_BOT_ID = 123456789


@dataclass(frozen=True, slots=True)
class SentCall:
    """One recorded Bot API call."""

    method: TelegramMethod[Any]

    @property
    def name(self) -> str:
        return type(self.method).__name__


class FakeSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[SentCall] = []
        self._failures: list[BaseException] = []
        self._message_id = 0

    def fail_next(self, *errors: BaseException) -> None:
        self._failures.extend(errors)

    async def close(self) -> None:
        return None

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[TelegramType],
        timeout: int | None = None,  # noqa: ASYNC109 - BaseSession's signature
    ) -> TelegramType:
        if self._failures:
            raise self._failures.pop(0)
        self.calls.append(SentCall(method))
        if isinstance(method, SendMessage):
            self._message_id += 1
            message = Message(
                message_id=self._message_id,
                date=datetime.now(UTC),
                chat=Chat(id=int(str(method.chat_id)), type="private"),
                from_user=User(id=FAKE_BOT_ID, is_bot=True, first_name="Bot"),
                text=method.text,
            )
            return cast(TelegramType, message)
        return cast(TelegramType, True)

    async def stream_content(  # pragma: no cover - never used
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,  # noqa: ASYNC109 - BaseSession's signature
        chunk_size: int = 65536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes]:
        raise NotImplementedError
        yield b""


class FakeBot(Bot):
    def __init__(self, token: str = DEV_TG_BOT_TOKEN) -> None:
        self.fake_session = FakeSession()
        super().__init__(token=token, session=self.fake_session)

    @property
    def calls(self) -> list[SentCall]:
        return self.fake_session.calls

    @property
    def messages(self) -> list[SendMessage]:
        """Every ``sendMessage`` call, in order."""
        return [c.method for c in self.calls if isinstance(c.method, SendMessage)]

    def fail_next(self, *errors: BaseException) -> None:
        self.fake_session.fail_next(*errors)

    def reset(self) -> None:
        self.fake_session.calls.clear()
