"""Where bundled files live (inside the .exe folder, or the source tree)."""
from __future__ import annotations

import os
import sys


def resource_dir() -> str:
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
