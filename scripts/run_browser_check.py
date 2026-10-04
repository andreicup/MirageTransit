"""Start an ephemeral lab and run browser checks; always stop all child processes."""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from lab_support import Lab  # noqa: E402

lab = Lab()
try:
    subprocess.run(["node", "scripts/browser_check.cjs", str(lab.directory)], check=True)
finally:
    lab.close()
