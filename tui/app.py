"""Textual application: interactive server setup."""

import asyncio
import os
import shlex

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
    Markdown,
    RichLog,
    Static,
)

from .tasks import SETUP_ORDER, TASKS
from .tasks.base import Step, Task
from .tasks.vpn import TAILSCALE_TASK, WIREGUARD_TASK


def is_root() -> bool:
    """Return True when running with root privileges (POSIX only)."""
    return hasattr(os, "geteuid") and os.geteuid() == 0


def build_command(step: Step, root: bool) -> str:
    """Build the shell command for a step, wrapping privileged steps in sudo."""
    if step.privileged and not root:
        return f"sudo -n sh -c {shlex.quote(step.cmd)}"
    return step.cmd


async def run_steps(steps: tuple[Step, ...], log: RichLog, root: bool) -> None:
    """Execute a sequence of steps, streaming output into a RichLog."""
    for step in steps:
        log.write(f"\n[bold cyan]── {step.title} ──[/]")
        proc = await asyncio.create_subprocess_shell(
            build_command(step, root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        assert proc.stdout is not None
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            log.write(line.decode("utf-8", errors="replace").rstrip())
            await asyncio.sleep(0)
        code = await proc.wait()
        if code != 0:
            log.write(f"[bold red]✗ {step.title} failed (exit {code})[/]")
        else:
            log.write("[green]✓ done[/]")


class ConfirmModal(ModalScreen[bool]):
    """Ask for confirmation before a destructive task."""

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static("Warning", classes="title")
            yield Markdown(self.message)
            with Horizontal(classes="buttons"):
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
            yield Static("VPN Selection", classes="title")
            yield Static("Choose how to set up secure remote access.")
            with Horizontal(classes="buttons"):
                yield Button("Skip", variant="default", id="skip")
                yield Button("WireGuard", variant="primary", id="wireguard")
                yield Button("Tailscale", variant="primary", id="tailscale")

    @on(Button.Pressed, "#tailscale")
    def _tailscale(self) -> None:
        self.dismiss("tailscale")

    @on(Button.Pressed, "#wireguard")
    def _wireguard(self) -> None:
        self.dismiss("wireguard")

    @on(Button.Pressed, "#skip")
    def _skip(self) -> None:
        self.dismiss("skip")


class MainScreen(Screen):
    """Main menu listing all available tasks."""

    BINDINGS = [Binding("q", "quit", "Quit")]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="main-body"):
            yield Static("Platypus Server Setup", classes="main-title")
            yield Static(
                "Select a task to configure this Linux server.",
                classes="subtitle",
            )
            with ListView(id="task-list"):
                yield ListItem(
                    Label("Sequential Setup (step-by-step)"), id="sequential"
                )
                for task in TASKS:
                    yield ListItem(Label(task.title))
        yield Footer()

    @on(ListView.Selected, "#task-list")
    def _on_selected(self, event: ListView.Selected) -> None:
        index = self.query_one("#task-list", ListView).index
        if index is None:
            return
        if index == 0:
            self.app.push_screen(SequentialSetupScreen())
        elif index - 1 < len(TASKS):
            self.app.push_screen(TaskScreen(TASKS[index - 1]))


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
            yield RichLog(id="output", wrap=True, markup=True, highlight=True)
        with Horizontal(id="task-actions"):
            yield Button("Run", variant="success", id="run")
            yield Button("Back", variant="default", id="back")
        yield Footer()

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
        self.query_one("#run", Button).disabled = True
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
        await run_steps(self._task_def.steps, log, is_root())
        log.write("\n[bold green]Task finished.[/]")
        self.running = False
        self.query_one("#run", Button).disabled = False

    def action_run(self) -> None:
        self._on_run()

    def action_back(self) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, "#back")
    def _on_back(self) -> None:
        self.action_back()


class SequentialSetupScreen(Screen):
    """Runs the full setup one stage at a time, in order."""

    BINDINGS = [
        Binding("s", "start", "Start"),
        Binding("b", "back", "Back"),
        Binding("escape", "back", "Back"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.plan = list(SETUP_ORDER)
        self.running = False

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="setup-body"):
            yield Static("Sequential Setup", classes="task-title")
            yield Markdown(
                "Runs the server setup **stage by stage**, in a safe order. "
                "Stages with a warning (SSH hardening, UFW) ask for confirmation "
                "before they run, and you can skip any of them."
            )
            yield Static("Plan", classes="section")
            for i, task in enumerate(self.plan, start=1):
                yield Static(f"{i}. {task.title}", classes="plan-item")
            yield Static(
                f"{len(self.plan) + 1}. VPN (Tailscale or WireGuard)",
                classes="plan-item",
            )
            yield Static("Output", classes="section")
            yield RichLog(id="output", wrap=True, markup=True, highlight=True)
        with Horizontal(id="task-actions"):
            yield Button("Start", variant="success", id="start")
            yield Button("Back", variant="default", id="back")
        yield Footer()

    @on(Button.Pressed, "#start")
    def _on_start(self) -> None:
        if self.running:
            return
        self.running = True
        self.query_one("#start", Button).disabled = True
        self._run_sequence()

    @work(exclusive=True, group="setup")
    async def _run_sequence(self) -> None:
        log = self.query_one("#output", RichLog)
        root = is_root()
        total = len(self.plan) + 1
        for index, task in enumerate(self.plan, start=1):
            await self._run_stage(index, total, task, log, root)
        await self._run_vpn_stage(total, total, log, root)
        log.write("\n[bold green]Sequential setup complete![/]")
        self.running = False
        self.query_one("#start", Button).label = "Done"

    async def _run_stage(
        self, index: int, total: int, task: Task, log: RichLog, root: bool
    ) -> None:
        log.write(f"\n[bold yellow]══ Stage {index}/{total}: {task.title} ══[/]")
        if task.warning:
            ok = await self.app.push_screen(
                ConfirmModal(task.warning), wait_for_dismiss=True
            )
            if not ok:
                log.write("[dim]Skipped by user.[/]")
                return
        await run_steps(task.steps, log, root)

    async def _run_vpn_stage(
        self, index: int, total: int, log: RichLog, root: bool
    ) -> None:
        log.write(
            f"\n[bold yellow]══ Stage {index}/{total}: VPN (Tailscale or WireGuard) ══[/]"
        )
        choice = await self.app.push_screen(VpnChoiceModal(), wait_for_dismiss=True)
        if choice == "skip":
            log.write("[dim]VPN skipped by user.[/]")
            return
        task = TAILSCALE_TASK if choice == "tailscale" else WIREGUARD_TASK
        await run_steps(task.steps, log, root)

    def action_start(self) -> None:
        self._on_start()

    def action_back(self) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, "#back")
    def _on_back(self) -> None:
        self.action_back()


class PlatypusApp(App):
    """Top-level Textual app."""

    TITLE = "Platypus Server Setup"
    BINDINGS = [Binding("q", "quit", "Quit")]

    CSS = """
    Screen {
        layout: vertical;
    }

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

    #task-body {
        padding: 1 2;
        height: 1fr;
    }

    #setup-body {
        padding: 1 2;
        height: 1fr;
    }

    .plan-item {
        padding: 0 1;
    }

    .task-title {
        text-style: bold;
        padding: 1 0;
    }

    .section {
        color: $text-muted;
        padding-top: 1;
        padding-bottom: 1;
    }

    #output {
        height: 1fr;
        border: round $primary;
    }

    .warning {
        color: $warning;
        margin-top: 1;
    }

    #task-actions {
        padding: 1 2;
        height: auto;
        align: center middle;
    }

    #task-actions Button {
        margin: 0 1;
    }

    #dialog {
        width: 70;
        height: auto;
        border: thick $warning;
        background: $surface;
        padding: 1 2;
    }

    #dialog .title {
        text-style: bold;
        color: $warning;
        padding-bottom: 1;
    }

    #dialog .buttons {
        align: right middle;
        margin-top: 1;
    }

    #dialog Button {
        margin-left: 1;
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


def main() -> None:
    """Run the TUI."""
    PlatypusApp().run()


if __name__ == "__main__":
    main()
