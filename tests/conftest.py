"""Import the core package without executing the Home Assistant adapter.

``custom_components/siem/__init__.py`` imports Home Assistant. The core is
tested without it, so the package objects above ``core`` are registered as
bare namespace modules pointing at the right directories.
"""

from __future__ import annotations

from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]


def _namespace(name: str, path: Path) -> None:
    module = types.ModuleType(name)
    module.__path__ = [str(path)]  # type: ignore[attr-defined]
    sys.modules.setdefault(name, module)


_namespace("custom_components", ROOT / "custom_components")
_namespace("custom_components.siem", ROOT / "custom_components" / "siem")
