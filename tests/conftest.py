import sys
from pathlib import Path

# Dynamically inject the project root to path so all test imports resolve seamlessly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
