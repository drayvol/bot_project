"""Точка входа бота: long polling, FSM в Redis."""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage

from bot import db
from bot.config import BOT_TOKEN, REDIS_URL, ensure_dirs
from bot.handlers import router

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(name)s: %(message)s')


async def main():
    ensure_dirs()
    db.init_db()

    bot = Bot(BOT_TOKEN)
    dp = Dispatcher(storage=RedisStorage.from_url(REDIS_URL))
    dp.include_router(router)

    await bot.delete_webhook(drop_pending_updates=False)
    logging.info('Бот запущен (long polling)')
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())
