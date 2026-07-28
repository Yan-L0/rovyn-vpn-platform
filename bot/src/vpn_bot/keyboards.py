from urllib.parse import urlencode

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo


def main_menu(miniapp_url: str, start_param: str | None = None) -> InlineKeyboardMarkup:
    query = urlencode({"start": start_param}) if start_param else ""
    app_url = f"{miniapp_url.rstrip('/')}?{query}" if query else miniapp_url
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Личный кабинет",
                    web_app=WebAppInfo(url=app_url),
                )
            ],
        ]
    )
