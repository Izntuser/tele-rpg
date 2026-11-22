"""Local development bot: ``python -m app.bot.polling`` (ARCHITECTURE §3 ``bot-dev``).

Long polling instead of the webhook, same dispatcher and handlers. It removes any webhook
first (Telegram refuses getUpdates while one is set) and refuses to start on the fake token,
which can never reach Telegram.
"""

import asyncio
import logging

from app.bot.dispatcher import SessionMiddleware, build_dispatcher, close_bot, get_bot
from app.bot.fake import FakeBot
from app.db.session import dispose_engine, get_sessionmaker

log = logging.getLogger("app.bot.polling")


async def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    bot = get_bot()
    if isinstance(bot, FakeBot):
        log.error("TG_BOT_TOKEN is the fake dev token (or APP_ENV=test); set a real dev bot token")
        return 1
    dp = build_dispatcher()
    dp.update.outer_middleware(SessionMiddleware(get_sessionmaker()))
    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot, allowed_updates=["message"], handle_signals=True)
    finally:
        await close_bot()
        await dispose_engine()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
