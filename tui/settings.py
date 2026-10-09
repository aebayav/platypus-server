"""User settings for the platypus TUI: interface mode and target profile.

Two settings keep the interface from getting overwhelming:

``mode``
    How much of the interface to show:
    - ``simple`` — essentials only (Docker, proxy, hardening, firewall, VPN)
    - ``full``   — every available task, including advanced tools

``target``
    What kind of server is being set up:
    - ``home`` — home server behind NAT (VPN for remote access, LAN services)
    - ``vps``  — public VPS (reverse proxy + HTTPS, fail2ban, no VPN)

Settings persist in a small YAML file (``~/.config/platypus/config.yml`` by
default; override the location with ``PLATYPUS_CONFIG``).  Values are resolved
with this precedence:

    command-line flag > environment variable > config file > default
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

MODES = ("simple", "full")
TARGETS = ("home", "vps")

DEFAULT_MODE = "full"
DEFAULT_TARGET = "home"

CONFIG_ENV = "PLATYPUS_CONFIG"
MODE_ENV = "PLATYPUS_MODE"
TARGET_ENV = "PLATYPUS_TARGET"


def default_config_path() -> Path:
    """Return the config file path (respects ``PLATYPUS_CONFIG``)."""
    override = os.environ.get(CONFIG_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "platypus" / "config.yml"


@dataclass(frozen=True)
class Settings:
    """Resolved settings for one run."""

    mode: str = DEFAULT_MODE
    target: str = DEFAULT_TARGET

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(
                f"unknown mode {self.mode!r} (expected one of {MODES})"
            )
        if self.target not in TARGETS:
            raise ValueError(
                f"unknown target {self.target!r} (expected one of {TARGETS})"
            )

    @property
    def simple(self) -> bool:
        """True when running in simplified (essentials-only) mode."""
        return self.mode == "simple"

    def as_dict(self) -> dict[str, str]:
        """Plain dict suitable for YAML serialization."""
        return {"mode": self.mode, "target": self.target}


def load_config(path: Path | None = None) -> dict:
    """Read the config file; return ``{}`` when missing or unreadable."""
    path = path or default_config_path()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def save_config(settings: Settings, path: Path | None = None) -> Path:
    """Write the settings to disk and return the path used."""
    path = path or default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(settings.as_dict(), sort_keys=False),
        encoding="utf-8",
    )
    return path


def resolve(
    mode: str | None = None,
    target: str | None = None,
    path: Path | None = None,
) -> Settings:
    """Resolve settings: explicit args > env vars > config file > defaults."""
    cfg = load_config(path)
    return Settings(
        mode=mode or os.environ.get(MODE_ENV) or cfg.get("mode") or DEFAULT_MODE,
        target=target
        or os.environ.get(TARGET_ENV)
        or cfg.get("target")
        or DEFAULT_TARGET,
    )
