#!/usr/bin/env python3
"""Wrapper to run airport import from repo root."""

import subprocess
import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1] / "apps" / "api"
subprocess.run([sys.executable, "-m", "scripts.import_airports"], cwd=API_DIR, check=True)
