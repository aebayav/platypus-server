"""Headless smoke tests for the TUI."""

import asyncio

from textual.widgets import Button, ListView

from tui.app import (
    ConfirmModal,
    PlatypusApp,
    SequentialSetupScreen,
    VpnChoiceModal,
)


def test_main_menu_has_all_entries() -> None:
    async def run() -> int:
        app = PlatypusApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            items = list(app.screen.query_one("#task-list", ListView).children)
            return len(items)

    assert asyncio.run(run()) == 7


def test_sequential_screen_composes() -> None:
    async def run() -> str:
        app = PlatypusApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.push_screen(SequentialSetupScreen())
            await pilot.pause()
            return app.screen.query_one("#start", Button).label

    assert asyncio.run(run()) == "Start"


def test_confirm_modal_returns_true() -> None:
    async def run() -> bool:
        app = PlatypusApp()
        result: dict = {}
        async with app.run_test() as pilot:
            await pilot.pause()
            app.push_screen(ConfirmModal("test"), lambda r: result.update(ok=r))
            await pilot.pause()
            await pilot.click("#continue")
            await pilot.pause()
        return result["ok"]

    assert asyncio.run(run()) is True


def test_vpn_modal_returns_tailscale() -> None:
    async def run() -> str:
        app = PlatypusApp()
        result: dict = {}
        async with app.run_test() as pilot:
            await pilot.pause()
            app.push_screen(VpnChoiceModal(), lambda r: result.update(vpn=r))
            await pilot.pause()
            await pilot.click("#tailscale")
            await pilot.pause()
        return result["vpn"]

    assert asyncio.run(run()) == "tailscale"
