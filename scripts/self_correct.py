#!/usr/bin/env python3
"""DEPRECATED: Use embeddpilot.py instead. This script is kept for backwards compatibility."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from embeddpilot import main

if __name__ == "__main__":
    main()
