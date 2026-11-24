"""Read the recipe module state for the dashboard.

A standalone, framework-free reader so the Flask layer stays thin and
the reading logic is unit-testable: schema v2 ``mounted`` sets, the v1
single-``active`` fallback, and robustness against missing or corrupt
files.  Never raises.
"""

from __future__ import annotations

from pathlib import Path


def _dir_size_mb(path: Path) -> float:
    try:
        total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    except OSError:
        return 0.0
    return round(total / (1024 * 1024), 1)


def read(state_file: Path, roles_dir: Path) -> dict:
    """Return {"mounted": [...], "dormant": [...], "history": [...]}."""
    mounted_names: list[str] = []
    history: list[dict] = []

    try:
        import yaml

        with state_file.open(encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    except Exception:  # noqa: BLE001 — missing/corrupt file must not raise
        raw = {}

    if isinstance(raw, dict):
        mounted = raw.get("mounted")
        if isinstance(mounted, list):
            mounted_names = [str(n) for n in mounted]
        elif isinstance(raw.get("active"), str):
            # v1 fallback: the single active role is a one-element set.
            mounted_names = [raw["active"]]
        history = [h for h in (raw.get("history") or []) if isinstance(h, dict)]

    def _activated_at(name: str) -> str | None:
        for entry in reversed(history):
            if entry.get("role") == name and entry.get("deactivated_at") is None:
                return str(entry.get("activated_at") or "") or None
        return None

    mounted_out = [
        {
            "name": name,
            "activated_at": _activated_at(name),
            "data_size_mb": (
                _dir_size_mb(roles_dir / name / "data")
                if (roles_dir / name / "data").exists()
                else 0.0
            ),
        }
        for name in mounted_names
    ]

    dormant_out: list[dict] = []
    if roles_dir.is_dir():
        for d in sorted(roles_dir.iterdir()):
            if not d.is_dir() or d.name in mounted_names:
                continue
            last_active = next(
                (
                    h.get("deactivated_at")
                    for h in reversed(history)
                    if h.get("role") == d.name
                ),
                None,
            )
            dormant_out.append(
                {
                    "name": d.name,
                    "configured": (d / "answers.yml").exists(),
                    "last_active": str(last_active) if last_active else None,
                    "data_size_mb": (
                        _dir_size_mb(d / "data") if (d / "data").exists() else 0.0
                    ),
                }
            )

    return {
        "mounted": mounted_out,
        "dormant": dormant_out,
        "history": history[-10:],
    }
