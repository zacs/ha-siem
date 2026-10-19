"""Shared test setup.

The core tests need nothing but pytest. When Home Assistant's test plugin is
installed, the tests under ``ha/`` run too, against a real Home Assistant
core. Without it, ``custom_components/siem/__init__.py`` cannot be imported, so
the package objects above ``core`` are registered as bare namespace modules and
``ha/`` is skipped.
"""

from __future__ import annotations

from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]

try:
    import pytest_homeassistant_custom_component  # noqa: F401
except ImportError:
    HAS_HA = False
    for name, path in (("custom_components", ROOT / "custom_components"), ("custom_components.siem", ROOT / "custom_components" / "siem")):
        module = types.ModuleType(name)
        module.__path__ = [str(path)]  # type: ignore[attr-defined]
        sys.modules.setdefault(name, module)
else:
    HAS_HA = True

pytest_plugins = ["pytest_homeassistant_custom_component"] if HAS_HA else []
collect_ignore = [] if HAS_HA else ["ha"]
