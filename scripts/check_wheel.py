"""Check packaged resources and entrypoint in a clean environment outside source tree."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from miragetransit import __version__

EXPECTED = "598421389befd84e873ad11306c68f53f8afd519cd3cb77beff90e61bf213b09"


def main() -> None:
    wheels = list(Path("dist").glob(f"miragetransit-{__version__}-*.whl"))
    if len(wheels) != 1:
        raise ValueError("build exactly one wheel first")
    wheel = wheels[0].resolve()
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        subprocess.run(["uv", "venv", str(root / "env"), "--python", sys.executable], check=True)
        python = root / "env" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        subprocess.run(
            ["uv", "pip", "install", "--python", str(python), "--no-deps", str(wheel)], check=True
        )
        result = subprocess.run(
            [str(python), "-m", "miragetransit", "demo"],
            cwd=root,
            env=environment,
            check=True,
            text=True,
            capture_output=True,
        )
        data = json.loads(result.stdout)
        if data["trace_sha256"] != EXPECTED or data["ticks"] != 600:
            raise ValueError("installed wheel does not match the golden 60-second trace")
        entrypoint = (
            root / "env" / ("Scripts/miragetransit.exe" if os.name == "nt" else "bin/miragetransit")
        )
        for arguments in (
            ["journal-demo", "--db", "original.sqlite", "--run", "wheel-demo"],
            [
                "run-export",
                "--db",
                "original.sqlite",
                "--run",
                "wheel-demo",
                "--output",
                "scenario.json",
            ],
            ["replay", "--input", "scenario.json"],
            ["run-import", "--db", "imported.sqlite", "--input", "scenario.json"],
        ):
            checked = subprocess.run(
                [str(entrypoint), *arguments],
                cwd=root,
                env=environment,
                check=True,
                text=True,
                capture_output=True,
            )
            if arguments[0] in ("replay", "run-import"):
                if not json.loads(checked.stdout)["verified"]:
                    raise ValueError("wheel journal scenario did not verify")
    print("PASS: clean wheel, profile, CLI, golden trace, SQLite export/replay/import")


if __name__ == "__main__":
    main()
