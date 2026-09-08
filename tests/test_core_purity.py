"""The core package must never import Home Assistant."""

from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / "custom_components" / "siem" / "core"


def test_core_has_no_homeassistant_imports():
    for path in CORE.glob("*.py"):
        for line in path.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")):
                assert "homeassistant" not in stripped, f"{path.name}: {stripped}"
