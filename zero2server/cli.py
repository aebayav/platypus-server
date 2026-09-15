"""Interactive CLI flow for zero-to-server (stdlib-only)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .catalog import CATALOG
from .generator import generate
from .runner import RunnerError, compose_available, install_watchtower_cron, run_compose


def _select_services() -> list[str]:
    print("Available services:")
    for index, item in enumerate(CATALOG, start=1):
        print(f"  {index}. {item['title']} — {item['description']}")
    print("\nEnter numbers separated by commas (e.g. '1,3'), or 'all':")
    raw = input("> ").strip().lower()

    if raw in ("", "all"):
        return [item["key"] for item in CATALOG]

    keys: list[str] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            keys.append(CATALOG[int(part) - 1]["key"])
        except (ValueError, IndexError):
            continue
    return keys


def _ask(prompt: str, default: str = "") -> str:
    if default:
        return input(f"{prompt} [{default}]: ").strip() or default
    return input(f"{prompt}: ").strip()


def _check_existing_compose(out_dir: str) -> bool:
    """Return True if the user wants to continue (overwrite or no conflict)."""
    compose_file = Path(out_dir) / "docker-compose.yml"
    if not compose_file.exists():
        return True
    print(f"\n  ! docker-compose.yml already exists in '{out_dir}'.")
    choice = input("    Overwrite? [y/N]: ").strip().lower()
    return choice in ("y", "yes")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="zero-to-server",
        description="Generate a personalised docker-compose setup and optionally run it.",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="After generating, run `docker compose up -d` immediately.",
    )
    parser.add_argument(
        "--install-cron",
        action="store_true",
        dest="install_cron",
        help="Install a daily cron job to restart Watchtower (requires root).",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        dest="out_dir",
        metavar="DIR",
        help="Output directory for generated files (default: prompted interactively).",
    )
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Preflight: warn if --run requested but docker compose unavailable
    # ------------------------------------------------------------------
    if args.run and not compose_available():
        print(
            "WARNING: `docker compose` is not available on this system.\n"
            "  Install Docker Engine with the Compose plugin first.\n"
            "  Continuing in generate-only mode.\n",
            file=sys.stderr,
        )
        args.run = False

    # ------------------------------------------------------------------
    # Interactive setup flow
    # ------------------------------------------------------------------
    print("zero-to-server — generate a personalized docker-compose setup\n")

    selected = _select_services()
    if not selected:
        print("No services selected. Exiting.")
        return
    print("\nSelected: " + ", ".join(selected))

    domain = _ask("Domain for HTTPS (leave empty for local-only)")

    email: str | None = None
    if domain:
        if "caddy" not in selected:
            selected.append("caddy")
            print("→ Caddy added automatically to serve " + domain)
        email = _ask("Email for Let's Encrypt (optional)") or None

    out_dir = args.out_dir or _ask("Output directory", default=".")

    # Check for existing compose file before generating
    if not _check_existing_compose(out_dir):
        print("Aborted.")
        return

    written = generate(selected, domain, email, out_dir)

    print("\nGenerated:")
    for path in written:
        print("  ✓ " + path)

    # ------------------------------------------------------------------
    # Optional: run docker compose
    # ------------------------------------------------------------------
    if args.run:
        print()
        try:
            run_compose(out_dir)
            print("\n✓ Stack is up. Check running containers with: docker compose ps")
        except RunnerError as exc:
            print(f"\nERROR: {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        print("\nNext steps:")
        print("  cd " + (out_dir if out_dir != "." else "."))
        print("  docker compose up -d")

    # ------------------------------------------------------------------
    # Optional: install watchtower cron
    # ------------------------------------------------------------------
    if args.install_cron:
        if "watchtower" not in selected:
            print(
                "\nINFO: Watchtower was not selected — skipping cron install.",
                file=sys.stderr,
            )
        else:
            print()
            try:
                install_watchtower_cron(out_dir)
            except RunnerError as exc:
                print(f"\nERROR: {exc}", file=sys.stderr)
                sys.exit(1)


if __name__ == "__main__":
    main()
