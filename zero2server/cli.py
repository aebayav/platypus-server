"""Interactive CLI flow for zero-to-server (stdlib-only)."""

from __future__ import annotations

from .catalog import CATALOG
from .generator import generate


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


def main() -> None:
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

    out_dir = _ask("Output directory", default=".")

    written = generate(selected, domain, email, out_dir)

    print("\nGenerated:")
    for path in written:
        print("  ✓ " + path)
    print("\nNext steps:")
    print("  cd " + (out_dir if out_dir != "." else "."))
    print("  docker compose up -d")


if __name__ == "__main__":
    main()
