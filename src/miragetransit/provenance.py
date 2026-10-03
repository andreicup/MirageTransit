"""Runtime, dependency-lock and simulation-source identity shared by storage and replay."""

import hashlib
import platform
from importlib.resources import files


def runtime_stamp() -> dict[str, str]:
    digest = hashlib.sha256()
    for name in ("models.py", "core.py", "intents.py", "profile.py", "checkpoint.py"):
        digest.update(files("miragetransit").joinpath(name).read_bytes())
    return {
        "runtime": platform.python_version(),
        "implementation": platform.python_implementation(),
        "engine_sha256": digest.hexdigest(),
        "dependency_lock_sha256": files("miragetransit")
        .joinpath("dependency-lock.sha256")
        .read_text()
        .strip(),
    }
