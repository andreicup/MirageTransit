import json
import os
import subprocess
import sys
import unittest


class ProcessTests(unittest.TestCase):
    def test_hash_is_stable_across_process_hash_seeds(self) -> None:
        hashes = set()
        for seed in ("0", "1", "98765"):
            environment = dict(os.environ, PYTHONHASHSEED=seed)
            result = subprocess.run(
                [sys.executable, "-m", "miragetransit", "demo"],
                check=True,
                text=True,
                capture_output=True,
                env=environment,
            )
            hashes.add(json.loads(result.stdout)["trace_sha256"])
        self.assertEqual(
            hashes,
            {"598421389befd84e873ad11306c68f53f8afd519cd3cb77beff90e61bf213b09"},
        )


if __name__ == "__main__":
    unittest.main()
