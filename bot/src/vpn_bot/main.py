from __future__ import annotations

import asyncio
import logging
import re

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import CommandStart
from aiogram.types import MenuButtonWebApp, Message, WebAppInfo

from vpn_bot.config import Settings
from vpn_bot.keyboards import main_menu

START_PARAMETER = re.compile(r"^(?:ref_[A-Za-z0-9_-]{4,48}|[A-Za-z0-9_-]{1,64})$")
router = Router()


@router.message(CommandStart())
async def start(message: Message, settings: Settings) -> None:
    raw_argument = ""
    if message.text:
        _, _, raw_argument = message.text.partition(" ")
        raw_argument = raw_argument.strip()
    start_parameter = (
        raw_argument if raw_argument and START_PARAMETER.fullmatch(raw_argument) else None
    )
    first_name = message.from_user.first_name if message.from_user else ""
    greeting = (
        f"Здравствуйте, {first_name}.\n\n"
        "Подключение VPN, подписка и устройства доступны в личном кабинете."
    )
    await message.answer(
        greeting,
        reply_markup=main_menu(str(settings.MINIAPP_PUBLIC_URL), start_parameter),
    )


async def run() -> None:
    settings = Settings()
    logging.basicConfig(level=logging.INFO)
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN.get_secret_value())
    dispatcher = Dispatcher()
    dispatcher["settings"] = settings
    dispatcher.include_router(router)
    try:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="Открыть VPN",
                web_app=WebAppInfo(url=str(settings.MINIAPP_PUBLIC_URL)),
            )
        )
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        await bot.session.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
