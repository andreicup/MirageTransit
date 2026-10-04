"""Create separate role config files for local Docker; no credentials in Compose."""

import argparse
import json
import os
from pathlib import Path

from miragetransit.service import initialize

parser = argparse.ArgumentParser()
parser.add_argument("--uid", type=int, default=1000)
parser.add_argument("--gid", type=int, default=1000)
args = parser.parse_args()
if args.uid <= 0 or args.gid <= 0:
    raise ValueError("application UID/GID must be nonzero")
path = Path("runs/container")
initialize(path)
for role in ("core", "decoy", "mqtt", "analyst"):
    file = path / f"{role}.json"
    config = json.loads(file.read_bytes())
    if role == "core":
        config["db"] = "/data/lab.sqlite"
    else:
        config["core_url"] = "http://core:8760"
    file.write_text(json.dumps(config, indent=2) + "\n")
    # Non-root image user 1000 reads only its own mount. Never world-readable secrets.
    os.chown(file, args.uid, args.gid)
data = path / "data"
data.mkdir(mode=0o700)
os.chown(data, args.uid, args.gid)
print("Prepared local role configs. Read runs/container/analyst.json for the console key.")
