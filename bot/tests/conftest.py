from __future__ import annotations

import sys
from pathlib import Path


BOT_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(BOT_SRC))
