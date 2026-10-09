"""Headless smoke tests for the TUI."""

import asyncio

from textual.widgets import Button, ListView

from tui.app import (
    ConfirmModal,
    PlatypusApp,
    SequentialSetupScreen,
    SettingsScreen,
    VpnChoiceModal,
)
from tui.settings import Settings
from tui.tasks import setup_order, visible_tasks


def _menu_item_count(settings: Settings) -> int:
    """Compose the app with the given settings and count menu entries."""

    async def run() -> int:
        app = PlatypusApp(settings=settings)
        async with app.run_test() as pilot:
            await pilot.pause()
            return len(app.screen.query_one("#task-list", ListView).children)

    return asyncio.run(run())


def test_main_menu_full_home() -> None:
    # +2 for the "Sequential Setup" and "Settings" entries
    expected = len(visible_tasks("home", "full")) + 2
    assert _menu_item_count(Settings(mode="full", target="home")) == expected


def test_main_menu_follows_settings() -> None:
    simple_vps = _menu_item_count(Settings(mode="simple", target="vps"))
    full_home = _menu_item_count(Settings(mode="full", target="home"))
    assert simple_vps == len(visible_tasks("vps", "simple")) + 2
    assert full_home == len(visible_tasks("home", "full")) + 2
    assert simple_vps < full_home


def test_settings_change_rebuilds_menu(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PLATYPUS_CONFIG", str(tmp_path / "config.yml"))

    async def run() -> int:
        app = PlatypusApp(settings=Settings(mode="full", target="home"))
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen._on_settings_result(Settings(mode="simple", target="vps"))
            await pilot.pause()
            return len(app.screen.query_one("#task-list", ListView).children)

    assert asyncio.run(run()) == len(visible_tasks("vps", "simple")) + 2


def test_sequential_screen_composes() -> None:
    async def run() -> str:
        app = PlatypusApp(settings=Settings())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.push_screen(SequentialSetupScreen(Settings()))
            await pilot.pause()
            return app.screen.query_one("#start", Button).label

    assert asyncio.run(run()) == "Start"


def test_sequential_home_has_vpn_stage() -> None:
    async def run() -> bool:
        app = PlatypusApp(settings=Settings(target="home"))
        async with app.run_test() as pilot:
            await pilot.pause()
            app.push_screen(SequentialSetupScreen(Settings(target="home")))
            await pilot.pause()
            return bool(app.screen.query("#stage-vpn"))

    assert asyncio.run(run()) is True


def test_sequential_vps_has_no_vpn_stage() -> None:
    async def run() -> bool:
        app = PlatypusApp(settings=Settings(target="vps"))
        async with app.run_test() as pilot:
            await pilot.pause()
            app.push_screen(SequentialSetupScreen(Settings(target="vps")))
            await pilot.pause()
            return bool(app.screen.query("#stage-vpn"))

    assert asyncio.run(run()) is False


def test_sequential_plan_matches_setup_order() -> None:
    vps_plan = SequentialSetupScreen(Settings(target="vps")).plan
    assert [task.id for task in vps_plan] == [
        task.id for task in setup_order("vps", "full")
    ]


def test_settings_screen_saves_new_settings() -> None:
    async def run() -> Settings:
        app = PlatypusApp(settings=Settings(mode="full", target="home"))
        result: dict = {}
        async with app.run_test() as pilot:
            await pilot.pause()
            app.push_screen(SettingsScreen(), lambda r: result.update(settings=r))
            await pilot.pause()
            await pilot.click("#mode-simple")
            await pilot.click("#target-vps")
            await pilot.click("#save")
            await pilot.pause()
        return result["settings"]

    assert asyncio.run(run()) == Settings(mode="simple", target="vps")


def test_confirm_modal_returns_true() -> None:
    async def run() -> bool:
        app = PlatypusApp(settings=Settings())
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
        app = PlatypusApp(settings=Settings())
        result: dict = {}
        async with app.run_test() as pilot:
            await pilot.pause()
            app.push_screen(VpnChoiceModal(), lambda r: result.update(vpn=r))
            await pilot.pause()
            await pilot.click("#tailscale")
            await pilot.pause()
        return result["vpn"]

    assert asyncio.run(run()) == "tailscale"
