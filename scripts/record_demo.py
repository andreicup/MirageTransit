"""Record a captioned three-minute browser walkthrough of an ephemeral real lab."""

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from lab_support import Lab  # noqa: E402

output = Path(sys.argv[1] if len(sys.argv) > 1 else "runs/portfolio/miragetransit-demo.webm")
output.parent.mkdir(parents=True, exist_ok=True)
lab = Lab()
try:
    environment = dict(os.environ, MT_DEMO_PYTHON=sys.executable)
    subprocess.run(
        ["node", "scripts/record_demo.cjs", str(lab.directory), str(output)],
        env=environment,
        check=True,
    )
finally:
    lab.close()
