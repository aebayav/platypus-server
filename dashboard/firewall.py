"""UFW firewall rule reader."""
from __future__ import annotations

import re
import subprocess


def get_firewall_rules() -> dict:
    """Parse ``ufw status verbose`` into structured data."""
    try:
        result = subprocess.run(
            ["ufw", "status", "verbose"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except FileNotFoundError:
        return {"status": "unavailable", "rules": [], "error": "ufw not found"}
    except subprocess.TimeoutExpired:
        return {"status": "unavailable", "rules": [], "error": "ufw timed out"}

    if result.returncode != 0:
        # ufw exits non-zero when inactive on some distros
        output = result.stdout + result.stderr
        if "inactive" in output.lower():
            return {"status": "inactive", "rules": []}
        return {
            "status": "error",
            "rules": [],
            "error": output.strip() or "ufw failed",
        }

    lines = result.stdout.strip().splitlines()
    status = "unknown"
    rules: list[dict] = []
    in_rules = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("Status:"):
            status = stripped.split(":", 1)[1].strip()
            continue
        # The rules table starts after the dashed separator line
        if re.match(r"^-+\s+-+", stripped):
            in_rules = True
            continue
        if not in_rules or not stripped:
            continue
        parts = stripped.split()
        if len(parts) >= 3:
            rules.append(
                {"to": parts[0], "action": parts[1], "from": " ".join(parts[2:])}
            )
        elif len(parts) == 2:
            rules.append({"to": parts[0], "action": parts[1], "from": "Anywhere"})

    return {"status": status, "rules": rules}
