"""Repository paths shared by the validation suite."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]      # repository root
APP = ROOT / "app"
DATA = APP / "data"                              # git-ignored local GenBank files
CROSS_CHECK = DATA / "cross_check"
CONFIG = APP / "config"
VALIDATION = ROOT / "validation"
CONFIGS = VALIDATION / "configs"
OUTPUTS = VALIDATION / "outputs"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
