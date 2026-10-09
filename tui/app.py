"""Textual application: interactive server setup."""

import argparse
import asyncio
import contextlib
import os
import shlex

from rich.markup import escape
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Label,
    ListItem,
    ListView,
    LoadingIndicator,
    Markdown,
    RadioButton,
    RadioSet,
    RichLog,
    Static,
)

from .settings import MODES, TARGETS, Settings, resolve, save_config
from .tasks import has_vpn_stage, setup_order, visible_tasks
from .tasks.base import Step, Task
from .tasks.vpn import TAILSCALE_TASK, WIREGUARD_TASK

# Short descriptions shown in the main menu beneath each task title.
_TASK_HINTS: dict[str, str] = {
    "docker":     "Docker Engine + Compose plugin via get.docker.com",
    "caddy":      "Reverse proxy with automatic HTTPS",
    "ssh":        "Disable root/password login, tighten sshd options",
    "ufw":        "Firewall: allow SSH/HTTP/HTTPS, deny everything else",
    "tailscale":  "Zero-config VPN — authenticate via browser URL",
    "wireguard":  "Self-hosted VPN — manual peer configuration",
    "postgresql": "Relational database — installs PostgreSQL from distro repo",
    "redis":      "In-memory store — installs Redis with persistence enabled",
    "nginx":      "Web server — installs Nginx and verifies configuration",
    "certbot":    "TLS certificates — Certbot + Nginx plugin for Let's Encrypt",
    "sysupdate":  "Upgrade all system packages via apt-get",
    "backup":     "Archive directories to tar.gz, optional S3 upload",
}



def is_root() -> bool:
    """Return True when running with root privileges (POSIX only)."""
    return hasattr(os, "geteuid") and os.geteuid() == 0


def build_command(step: Step, root: bool) -> str:
    """Build the shell command for a step, wrapping privileged steps in sudo."""
    if step.privileged and not root:
        return f"sudo -n sh -c {shlex.quote(step.cmd)}"
    return step.cmd


async def _drain_output(proc: asyncio.subprocess.Process, log: RichLog) -> None:
    """Stream a process's stdout into the log, escaping markup characters."""
    assert proc.stdout is not None
    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        log.write(escape(line.decode("utf-8", errors="replace").rstrip()))
        await asyncio.sleep(0)


async def run_steps(steps: tuple[Step, ...], log: RichLog, root: bool) -> bool:
    """Execute a sequence of steps, streaming output into a RichLog.

    Returns True if all steps succeeded, False if any step failed.
    """
    all_ok = True
    for step in steps:
        log.write(f"\n[bold cyan]── {step.title} ──[/]")
        try:
            proc = await asyncio.create_subprocess_shell(
                build_command(step, root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            assert proc.stdout is not None
            reader = asyncio.create_task(_drain_output(proc, log))
            code = await proc.wait()
            # Drain remaining buffered output, then stop. A background child can
            # keep the pipe open after the shell exits, which would otherwise
            # block readline() forever.
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(asyncio.shield(reader), timeout=1.0)
            if not reader.done():
                reader.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await reader
            if code != 0:
                log.write(f"[bold red]  FAILED  {step.title} (exit {code})[/]")
                all_ok = False
            else:
                log.write("[green]  OK[/]")
        except Exception as exc:  # noqa: BLE001
            log.write(f"[bold red]  ERROR  {step.title}: {escape(str(exc))}[/]")
            all_ok = False
    return all_ok


# ---------------------------------------------------------------------------
# Modals
# ---------------------------------------------------------------------------


class ConfirmModal(ModalScreen[bool]):
    """Ask for confirmation before a destructive task."""

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static("! Caution", classes="dialog-title dialog-title--warn")
            yield Markdown(self.message)
            with Horizontal(classes="dialog-buttons"):
                yield Button("Cancel", variant="default", id="cancel")
                yield Button("Continue", variant="error", id="continue")

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed, "#continue")
    def _proceed(self) -> None:
        self.dismiss(True)


class VpnChoiceModal(ModalScreen[str]):
    """Ask which VPN to configure (or skip)."""

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static("VPN Selection", classes="dialog-title")
            yield Static(
                "Choose how this server should be reachable from outside.",
                classes="dialog-subtitle",
            )
            yield Button(
                "Install Tailscale — zero-config mesh VPN",
                variant="primary",
                id="tailscale",
                classes="vpn-button",
            )
            yield Button(
                "Install WireGuard — self-hosted VPN",
                variant="primary",
                id="wireguard",
                classes="vpn-button",
            )
            with Horizontal(classes="dialog-buttons"):
                yield Button("Skip VPN", variant="default", id="skip")

    @on(Button.Pressed, "#tailscale")
    def _tailscale(self) -> None:
        self.dismiss("tailscale")

    @on(Button.Pressed, "#wireguard")
    def _wireguard(self) -> None:
        self.dismiss("wireguard")

    @on(Button.Pressed, "#skip")
    def _skip(self) -> None:
        self.dismiss("skip")


# ---------------------------------------------------------------------------
# Screens
# ---------------------------------------------------------------------------


class MainScreen(Screen):
    """Main menu listing the tasks for the current profile."""

    BINDINGS = [Binding("q", "quit", "Quit")]

    def compose(self) -> ComposeResult:
        settings = getattr(self.app, "settings", None) or Settings()
        tasks = visible_tasks(settings.target, settings.mode)
        yield Header()
        with Vertical(id="main-body"):
            yield Static("Platypus Server Setup", classes="main-title")
            yield Static(
                self._subtitle(settings, len(tasks)),
                classes="subtitle",
            )
            with ListView(id="task-list"):
                # Sequential Setup — top entry, visually distinct
                with ListItem():
                    yield Label("Sequential Setup", classes="item-title item-title--highlight")
                    yield Label(
                        "Run all stages in order, with per-stage confirmation",
                        classes="item-hint",
                    )
                # Individual tasks
                for task in tasks:
                    hint = _TASK_HINTS.get(task.id, "")
                    with ListItem():
                        yield Label(task.title, classes="item-title")
                        if hint:
                            yield Label(hint, classes="item-hint")
                # Settings — bottom entry
                with ListItem():
                    yield Label("Settings", classes="item-title item-title--highlight")
                    yield Label(self._settings_hint(settings), classes="item-hint")
        yield Footer()

    @staticmethod
    def _subtitle(settings: Settings, task_count: int) -> str:
        profile = (
            "Home server — VPN for remote access"
            if settings.target == "home"
            else "VPS — public IP, HTTPS via reverse proxy"
        )
        mode = "simple" if settings.simple else "full"
        return f"Select a task ({task_count}) · {profile} · {mode} mode"

    @staticmethod
    def _settings_hint(settings: Settings) -> str:
        target = "home server" if settings.target == "home" else "VPS"
        mode = "simple" if settings.simple else "full"
        return f"Current: {target} · {mode} mode — press Enter to change"

    @on(ListView.Selected, "#task-list")
    def _on_selected(self, event: ListView.Selected) -> None:
        settings = self.app.settings
        tasks = visible_tasks(settings.target, settings.mode)
        index = self.query_one("#task-list", ListView).index
        if index is None:
            return
        if index == 0:
            self.app.push_screen(SequentialSetupScreen(settings))
        elif index <= len(tasks):
            self.app.push_screen(TaskScreen(tasks[index - 1]))
        else:
            self._open_settings()

    def _open_settings(self) -> None:
        self.app.push_screen(SettingsScreen(), self._on_settings_result)

    def _on_settings_result(self, new_settings: Settings | None) -> None:
        if new_settings is None:
            return
        self.app.settings = new_settings
        save_config(new_settings)
        self._rebuild_task_list()

    def _rebuild_task_list(self) -> None:
        settings = self.app.settings
        tasks = visible_tasks(settings.target, settings.mode)
        items: list[ListItem] = [
            ListItem(
                Label("Sequential Setup", classes="item-title item-title--highlight"),
                Label(
                    "Run all stages in order, with per-stage confirmation",
                    classes="item-hint",
                ),
            )
        ]
        for task in tasks:
            children: list = [Label(task.title, classes="item-title")]
            hint = _TASK_HINTS.get(task.id, "")
            if hint:
                children.append(Label(hint, classes="item-hint"))
            items.append(ListItem(*children))
        items.append(
            ListItem(
                Label("Settings", classes="item-title item-title--highlight"),
                Label(self._settings_hint(settings), classes="item-hint"),
            )
        )
        list_view = self.query_one("#task-list", ListView)
        list_view.clear()
        list_view.mount_all(items)
        list_view.index = 0
        self.query_one(".subtitle", Static).update(
            self._subtitle(settings, len(tasks))
        )


class SettingsScreen(Screen[Settings | None]):
    """Change the server target and the interface mode."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("b", "back", "Back"),
    ]

    def compose(self) -> ComposeResult:
        settings = getattr(self.app, "settings", None) or Settings()
        yield Header()
        with VerticalScroll(id="settings-body"):
            yield Static("Settings", classes="task-title")
            yield Markdown(
                "What kind of server is this, and how much of the menu "
                "should be shown? Changes are saved at once."
            )
            yield Static("Server target", classes="section")
            with RadioSet(id="target-set", compact=True):
                yield RadioButton(
                    "Home server — behind NAT, VPN for remote access",
                    value=settings.target == "home",
                    id="target-home",
                )
                yield RadioButton(
                    "VPS — public IP, reverse proxy + HTTPS",
                    value=settings.target == "vps",
                    id="target-vps",
                )
            yield Static("Interface", classes="section")
            with RadioSet(id="mode-set", compact=True):
                yield RadioButton(
                    "Simple — essentials only",
                    value=settings.simple,
                    id="mode-simple",
                )
                yield RadioButton(
                    "Full — every task",
                    value=not settings.simple,
                    id="mode-full",
                )
        with Horizontal(id="task-actions"):
            yield Button("Save", variant="success", id="save")
            yield Button("Back", variant="default", id="back")
        yield Footer()

    @on(Button.Pressed, "#save")
    def _on_save(self) -> None:
        target_set = self.query_one("#target-set", RadioSet)
        mode_set = self.query_one("#mode-set", RadioSet)
        target = "home" if target_set.pressed_button.id == "target-home" else "vps"
        mode = "simple" if mode_set.pressed_button.id == "mode-simple" else "full"
        self.dismiss(Settings(mode=mode, target=target))

    @on(Button.Pressed, "#back")
    def _on_back(self) -> None:
        self.dismiss(None)

    def action_back(self) -> None:
        self.dismiss(None)


class TaskScreen(Screen):
    """Shows one task's details and streams its command output."""

    BINDINGS = [
        Binding("r", "run", "Run"),
        Binding("b", "back", "Back"),
        Binding("escape", "back", "Back"),
    ]

    def __init__(self, task: Task) -> None:
        super().__init__()
        self._task_def = task
        self.running = False

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="task-body"):
            yield Static(self._task_def.title, classes="task-title")
            yield Markdown(self._task_def.description)
            if self._task_def.warning:
                yield Markdown(f"**Note:** {self._task_def.warning}", classes="warning")
            yield Static("Output", classes="section")
            yield Static(
                "Press [Run] or hit  r  to execute this task.",
                id="output-placeholder",
                classes="placeholder",
            )
            yield LoadingIndicator(id="spinner")
            yield RichLog(id="output", wrap=True, markup=True, highlight=True)
        with Horizontal(id="task-actions"):
            yield Button("Run", variant="success", id="run")
            yield Button("Back", variant="default", id="back")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#spinner", LoadingIndicator).display = False

    @on(Button.Pressed, "#run")
    def _on_run(self) -> None:
        if self.running:
            return
        if self._task_def.warning:
            self.app.push_screen(ConfirmModal(self._task_def.warning), self._start)
        else:
            self._start(True)

    def _start(self, confirmed: bool) -> None:
        if not confirmed:
            return
        self.running = True
        run_btn = self.query_one("#run", Button)
        run_btn.disabled = True
        run_btn.label = "Running..."
        self.query_one("#output-placeholder").display = False
        self.query_one("#spinner", LoadingIndicator).display = True
        log = self.query_one("#output", RichLog)
        log.clear()
        log.write(
            f"[bold]Starting task:[/] {self._task_def.title}\n"
            f"[dim]{'Root' if is_root() else 'Non-root — privileged steps use `sudo -n`'}[/]"
        )
        self._run_task()

    @work(exclusive=True, group="task")
    async def _run_task(self) -> None:
        log = self.query_one("#output", RichLog)
        ok = await run_steps(self._task_def.steps, log, is_root())
        self.query_one("#spinner", LoadingIndicator).display = False
        if ok:
            log.write("\n[bold green]Task finished successfully.[/]")
        else:
            log.write("\n[bold red]Task finished with errors — review output above.[/]")
        self.running = False
        run_btn = self.query_one("#run", Button)
        run_btn.label = "Run Again"
        run_btn.disabled = False

    def action_run(self) -> None:
        self._on_run()

    def action_back(self) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, "#back")
    def _on_back(self) -> None:
        self.action_back()


# Stage status markers (ASCII, no emoji)
_STAGE_DONE = "[green]  [DONE]   [/]"
_STAGE_RUNNING = "[bold yellow]  [ACTIVE] [/]"
_STAGE_PENDING = "  [ ]      "
_STAGE_SKIPPED = "[dim]  [SKIP]   [/]"


class SequentialSetupScreen(Screen):
    """Runs the full setup one stage at a time, in order."""

    BINDINGS = [
        Binding("s", "start", "Start"),
        Binding("b", "back", "Back"),
        Binding("escape", "back", "Back"),
    ]

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__()
        self.settings = settings or Settings()
        self.plan = setup_order(self.settings.target, self.settings.mode)
        self.has_vpn = has_vpn_stage(self.settings.target)
        self.running = False

    # ------------------------------------------------------------------
    # Compose
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="setup-body"):
            yield Static("Sequential Setup", classes="task-title")
            yield Markdown(self._description())
            yield Static("Stages", classes="section")
            for i, task in enumerate(self.plan, start=1):
                yield Static(
                    f"{_STAGE_PENDING}{i}. {task.title}",
                    id=f"stage-{task.id}",
                    classes="plan-item",
                    markup=True,
                )
            if self.has_vpn:
                vpn_index = len(self.plan) + 1
                yield Static(
                    f"{_STAGE_PENDING}{vpn_index}. VPN (Tailscale or WireGuard)",
                    id="stage-vpn",
                    classes="plan-item",
                    markup=True,
                )
            yield Static("Output", classes="section")
            yield LoadingIndicator(id="spinner")
            yield RichLog(id="output", wrap=True, markup=True, highlight=True)
        with Horizontal(id="task-actions"):
            yield Button("Start", variant="success", id="start")
            yield Button("Back", variant="default", id="back")
        yield Footer()

    def _description(self) -> str:
        base = (
            "Runs the server setup **stage by stage**, in a safe order. "
            "Stages with a warning (SSH hardening, UFW) ask for confirmation "
            "before they run, and you can skip any of them."
        )
        if self.has_vpn:
            return base + " The final stage asks for **Tailscale or WireGuard**."
        return (
            base + " This is a **VPS** — there is no VPN stage (public IP); "
            "Caddy handles HTTPS."
        )

    def on_mount(self) -> None:
        self.query_one("#spinner", LoadingIndicator).display = False

    # ------------------------------------------------------------------
    # Helpers: stage status updates
    # ------------------------------------------------------------------

    def _set_stage_status(self, stage_id: str, index: int, title: str, status: str) -> None:
        widget = self.query_one(f"#{stage_id}", Static)
        marker = {
            "running": _STAGE_RUNNING,
            "done": _STAGE_DONE,
            "skipped": _STAGE_SKIPPED,
            "pending": _STAGE_PENDING,
        }.get(status, _STAGE_PENDING)
        widget.update(f"{marker}{index}. {title}")

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    @on(Button.Pressed, "#start")
    def _on_start(self) -> None:
        if self.running:
            return
        self.running = True
        btn = self.query_one("#start", Button)
        btn.disabled = True
        btn.label = "Running..."
        self.query_one("#spinner", LoadingIndicator).display = True
        self._run_sequence()

    @work(exclusive=True, group="setup")
    async def _run_sequence(self) -> None:
        log = self.query_one("#output", RichLog)
        root = is_root()
        total = len(self.plan) + (1 if self.has_vpn else 0)
        for index, task in enumerate(self.plan, start=1):
            await self._run_stage(index, total, task, log, root)
        if self.has_vpn:
            await self._run_vpn_stage(total, total, log, root)
        else:
            log.write(
                "\n[dim]VPN stage skipped — VPS target (public IP, no VPN needed).[/]"
            )
        self.query_one("#spinner", LoadingIndicator).display = False
        log.write("\n[bold green]Sequential setup complete![/]")
        self.running = False
        btn = self.query_one("#start", Button)
        btn.label = "Done"
        btn.variant = "success"
        btn.disabled = True

    async def _run_stage(
        self, index: int, total: int, task: Task, log: RichLog, root: bool
    ) -> None:
        self._set_stage_status(f"stage-{task.id}", index, task.title, "running")
        log.write(f"\n[bold yellow]== Stage {index}/{total}: {task.title} ==[/]")
        if task.warning:
            ok = await self.app.push_screen(
                ConfirmModal(task.warning), wait_for_dismiss=True
            )
            if not ok:
                log.write("[dim]Skipped by user.[/]")
                self._set_stage_status(f"stage-{task.id}", index, task.title, "skipped")
                return
        await run_steps(task.steps, log, root)
        self._set_stage_status(f"stage-{task.id}", index, task.title, "done")

    async def _run_vpn_stage(
        self, index: int, total: int, log: RichLog, root: bool
    ) -> None:
        vpn_title = "VPN (Tailscale or WireGuard)"
        self._set_stage_status("stage-vpn", index, vpn_title, "running")
        log.write(f"\n[bold yellow]== Stage {index}/{total}: {vpn_title} ==[/]")
        choice = await self.app.push_screen(VpnChoiceModal(), wait_for_dismiss=True)
        if choice == "skip":
            log.write("[dim]VPN skipped by user.[/]")
            self._set_stage_status("stage-vpn", index, vpn_title, "skipped")
            return
        task = TAILSCALE_TASK if choice == "tailscale" else WIREGUARD_TASK
        await run_steps(task.steps, log, root)
        self._set_stage_status("stage-vpn", index, vpn_title, "done")

    def action_start(self) -> None:
        self._on_start()

    def action_back(self) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, "#back")
    def _on_back(self) -> None:
        self.action_back()


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------


class PlatypusApp(App):
    """Top-level Textual app."""

    TITLE = "Platypus Server Setup"
    BINDINGS = [Binding("q", "quit", "Quit")]

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__()
        self.settings = settings or resolve()

    CSS = """
    /* ------------------------------------------------------------------ */
    /* Global                                                               */
    /* ------------------------------------------------------------------ */
    Screen {
        layout: vertical;
    }

    /* ------------------------------------------------------------------ */
    /* Main screen                                                          */
    /* ------------------------------------------------------------------ */
    #main-body {
        padding: 1 2;
    }

    .main-title {
        text-style: bold;
        color: $accent;
        padding: 1 0;
    }

    .subtitle {
        color: $text-muted;
        padding-bottom: 1;
    }

    /* Task list items */
    .item-title {
        text-style: bold;
    }

    .item-title--highlight {
        color: $accent;
    }

    .item-hint {
        color: $text-muted;
        padding-left: 1;
    }

    /* ------------------------------------------------------------------ */
    /* Task / setup screens                                                 */
    /* ------------------------------------------------------------------ */
    #task-body {
        padding: 1 2;
        height: 1fr;
    }

    #setup-body {
        padding: 1 2;
        height: 1fr;
    }

    #settings-body {
        padding: 1 2;
        height: 1fr;
    }

    #settings-body RadioSet {
        margin: 0 1 0 1;
    }

    .task-title {
        text-style: bold;
        color: $accent;
        padding: 1 0;
    }

    .section {
        text-style: bold;
        color: $text-muted;
        padding-top: 1;
        padding-bottom: 0;
        border-bottom: solid $primary-darken-2;
    }

    /* Stage plan items */
    .plan-item {
        padding: 0 1;
    }

    /* Output area */
    .placeholder {
        color: $text-muted;
        padding: 1 1;
        border: dashed $primary-darken-2;
        margin-top: 1;
    }

    #spinner {
        height: 1;
        margin-top: 1;
    }

    #output {
        height: 1fr;
        border: round $primary;
        margin-top: 1;
    }

    .warning {
        color: $warning;
        margin-top: 1;
    }

    /* Action bar */
    #task-actions {
        dock: bottom;
        padding: 1 2;
        height: auto;
        align: center middle;
    }

    #task-actions Button {
        margin: 0 1;
    }

    /* ------------------------------------------------------------------ */
    /* Modals                                                               */
    /* ------------------------------------------------------------------ */
    #dialog {
        width: 76;
        height: auto;
        max-height: 90%;
        border: thick $surface-lighten-1;
        background: $surface;
        padding: 1 2;
    }

    .dialog-title {
        text-style: bold;
        padding-bottom: 1;
    }

    .dialog-title--warn {
        color: $warning;
    }

    .dialog-subtitle {
        color: $text-muted;
        padding-bottom: 1;
    }

    .dialog-buttons {
        align: right middle;
        margin-top: 1;
    }

    .dialog-buttons Button {
        margin-left: 1;
    }

    /* VPN choice buttons */
    .vpn-button {
        margin-top: 1;
        width: 100%;
    }
    """

    def on_mount(self) -> None:
        self.push_screen(MainScreen())
        if not is_root():
            self.notify(
                "Not running as root — privileged steps use `sudo -n`.",
                severity="warning",
                timeout=8,
            )


def main(argv: list[str] | None = None) -> None:
    """Run the TUI."""
    parser = argparse.ArgumentParser(
        prog="platypus-tui",
        description="Interactive Linux server setup (Textual).",
    )
    parser.add_argument(
        "--mode",
        choices=MODES,
        default=None,
        help=(
            "interface mode: 'simple' shows the essentials only, 'full' shows "
            "every task (default: PLATYPUS_MODE, then the saved settings, "
            "then 'full')"
        ),
    )
    parser.add_argument(
        "--target",
        choices=TARGETS,
        default=None,
        help=(
            "server target: 'home' for a home server behind NAT, 'vps' for a "
            "public VPS (default: PLATYPUS_TARGET, then the saved settings, "
            "then 'home')"
        ),
    )
    args = parser.parse_args(argv)
    PlatypusApp(settings=resolve(mode=args.mode, target=args.target)).run()


if __name__ == "__main__":
    main()
