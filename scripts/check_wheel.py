"""Check packaged resources and entrypoint in a clean environment outside source tree."""

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
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
        subprocess.run(
            [
                str(python),
                "-c",
                "from importlib.resources import files; "
                "assert all(files('miragetransit').joinpath('web',name).is_file() "
                "for name in ('analyst.html','analyst.js','decoy.html','decoy.js','style.css'))",
            ],
            cwd=root,
            env=environment,
            check=True,
        )
        subprocess.run(
            [str(entrypoint), "lab-init", "--directory", "lab", "--base-port", "28760"],
            cwd=root,
            env=environment,
            check=True,
            capture_output=True,
        )
        live = subprocess.Popen(
            [str(entrypoint), "lab", "--directory", "lab"],
            cwd=root,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                try:
                    with urllib.request.urlopen(
                        "http://127.0.0.1:28761/fleet", timeout=0.3
                    ) as response:
                        projection = json.load(response)
                    if len(projection["snapshot"]["states"]) == 3:
                        break
                except OSError:
                    time.sleep(0.1)
            else:
                raise ValueError("installed-wheel live lab did not start")
            with urllib.request.urlopen("http://127.0.0.1:28762/", timeout=2) as response:
                if b"PRIVATE ANALYST CONSOLE" not in response.read():
                    raise ValueError("installed-wheel analyst assets missing")
        finally:
            live.terminate()
            live.wait(timeout=10)
            if live.stderr:
                live.stderr.close()
    print("PASS: clean wheel, golden trace, SQLite replay/import, four-process lab and web assets")


if __name__ == "__main__":
    main()
