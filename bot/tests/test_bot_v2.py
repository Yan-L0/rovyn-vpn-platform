from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.types import MenuButtonWebApp

from vpn_bot.config import Settings
from vpn_bot.keyboards import main_menu
from vpn_bot import main as bot_main


MINIAPP_URL = "https://vpn.example/cabinet"


def make_settings() -> Settings:
    return Settings(
        _env_file=None,
        TELEGRAM_BOT_TOKEN="123456:test-token",
        MINIAPP_PUBLIC_URL=MINIAPP_URL,
    )


def assert_cabinet_only(markup: object, expected_url: str = MINIAPP_URL) -> None:
    keyboard = markup.inline_keyboard  # type: ignore[attr-defined]
    assert len(keyboard) == 1
    assert len(keyboard[0]) == 1
    button = keyboard[0][0]
    assert button.text == "Личный кабинет"
    assert button.web_app is not None
    assert button.web_app.url == expected_url
    assert button.callback_data is None


def test_main_menu_contains_only_cabinet_button() -> None:
    assert_cabinet_only(main_menu(MINIAPP_URL))


def test_main_menu_preserves_valid_start_parameter() -> None:
    assert_cabinet_only(
        main_menu(MINIAPP_URL, "ref_user-42"),
        f"{MINIAPP_URL}?start=ref_user-42",
    )


@pytest.mark.asyncio
async def test_start_greets_user_and_shows_only_cabinet() -> None:
    message = SimpleNamespace(
        text="/start ref_user-42",
        from_user=SimpleNamespace(first_name="Анна"),
        answer=AsyncMock(),
    )

    await bot_main.start(message, make_settings())

    message.answer.assert_awaited_once()
    text = message.answer.await_args.args[0]
    markup = message.answer.await_args.kwargs["reply_markup"]
    assert text.startswith("Здравствуйте, Анна.")
    assert_cabinet_only(markup, f"{MINIAPP_URL}?start=ref_user-42")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "handler",
    [bot_main.cabinet, bot_main.help_command, bot_main.payment_support],
)
async def test_service_commands_show_only_cabinet(handler: object) -> None:
    message = SimpleNamespace(answer=AsyncMock())

    await handler(message, make_settings())  # type: ignore[operator]

    message.answer.assert_awaited_once()
    assert_cabinet_only(message.answer.await_args.kwargs["reply_markup"])


@pytest.mark.asyncio
async def test_run_registers_only_v2_commands_and_open_vpn_menu_button(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = SimpleNamespace(
        set_my_commands=AsyncMock(),
        set_chat_menu_button=AsyncMock(),
        session=SimpleNamespace(close=AsyncMock()),
    )
    class FakeDispatcher:
        def __init__(self) -> None:
            self.start_polling = AsyncMock()
            self.workflow_data: dict[str, object] = {}

        def __setitem__(self, key: str, value: object) -> None:
            self.workflow_data[key] = value

        def include_router(self, router: object) -> None:
            self.router = router

        def resolve_used_update_types(self) -> list[str]:
            return ["message"]

    dispatcher = FakeDispatcher()

    monkeypatch.setattr(bot_main, "Settings", make_settings)
    monkeypatch.setattr(bot_main, "Bot", lambda token: bot)
    monkeypatch.setattr(bot_main, "Dispatcher", lambda: dispatcher)

    await bot_main.run()

    commands = bot.set_my_commands.await_args.args[0]
    assert [(command.command, command.description) for command in commands] == [
        ("cabinet", "Открыть личный кабинет"),
        ("help", "Помощь"),
        ("paysupport", "Поддержка по оплате"),
    ]
    menu_button = bot.set_chat_menu_button.await_args.kwargs["menu_button"]
    assert isinstance(menu_button, MenuButtonWebApp)
    assert menu_button.text == "Открыть VPN"
    assert menu_button.web_app.url == MINIAPP_URL
    bot.session.close.assert_awaited_once()
