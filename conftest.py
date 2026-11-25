from __future__ import annotations

import os
import sys
from pathlib import Path

# Keep root-collected hidden tests deterministic even when they call the
# default seed entry point themselves.
os.environ.setdefault("SORTBAY_SEED_DEMO_SCANS", "0")

BACKEND = Path(__file__).resolve().parent / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
