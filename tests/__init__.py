"""Make the repository's flat src layout importable in test runners."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
