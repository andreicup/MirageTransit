"""Ensure the packaged provenance matches the repository dependency lock."""

import hashlib
from pathlib import Path


def main() -> None:
    expected = Path("src/miragetransit/dependency-lock.sha256").read_text().strip()
    actual = hashlib.sha256(Path("uv.lock").read_bytes()).hexdigest()
    if expected != actual:
        raise ValueError("uv.lock changed; update the packaged dependency-lock.sha256")
    print("PASS: packaged dependency lock fingerprint")


if __name__ == "__main__":
    main()
