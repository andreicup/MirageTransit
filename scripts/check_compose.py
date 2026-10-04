"""Runtime acceptance on a Docker host; requires prepare.py + compose up --wait."""

import json
import subprocess
import time
import urllib.request


def container(role: str, code: str) -> None:
    subprocess.run(["docker", "compose", "exec", "-T", role, "python", "-c", code], check=True)


for port in (8761, 8762):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=5) as response:
        if response.status != 200:
            raise ValueError("unhealthy service")
with urllib.request.urlopen("http://127.0.0.1:8761/fleet", timeout=5) as response:
    first = json.load(response)["snapshot"]["tick"]
time.sleep(0.3)
with urllib.request.urlopen("http://127.0.0.1:8761/fleet", timeout=5) as response:
    if json.load(response)["snapshot"]["tick"] <= first:
        raise ValueError("tick loop is not running")

container(
    "portal",
    """
import json,os,socket
from miragetransit.rpc import Client
assert os.getuid()!=0
assert not os.path.exists('/data')
assert not os.path.exists('/config/analyst.json')
c=json.load(open('/config/decoy.json'))
client=Client(c['core_url'],c['key'])
assert client.call('state')['snapshot']['running']
for operation in ('events','evidence','export','stop'):
    try: client.call(operation)
    except ValueError as error: assert 'capability denied' in str(error)
    else: raise AssertionError('analyst capability leaked')
try: socket.create_connection(('analyst',8762),timeout=2)
except OSError: pass
else: raise AssertionError('decoy can reach analyst network')
""",
)
container(
    "analyst",
    """
import os,socket
assert os.getuid()!=0
assert not os.path.exists('/data')
assert not os.path.exists('/config/decoy.json')
try: socket.create_connection(('portal',8761),timeout=2)
except OSError: pass
else: raise AssertionError('analyst can reach decoy network')
""",
)
container(
    "core",
    """
import json
from pathlib import Path
from miragetransit.replay import verify
from miragetransit.rpc import Client
c=json.load(open('/config/core.json'))
a=Client('http://127.0.0.1:8760',c['analyst_key'])
a.call('stop')
assert verify(a.call('export'))['verified']
assert Path('/data/lab.sqlite').is_file()
""",
)
config = subprocess.run(
    ["docker", "compose", "config", "--format", "json"], capture_output=True, text=True, check=True
)
resolved = json.loads(config.stdout)
for service in resolved["services"].values():
    assert service["read_only"]
    assert "ALL" in service["cap_drop"]
    assert not service.get("privileged")
    for port in service.get("ports", []):
        assert port["host_ip"] == "127.0.0.1"
assert not resolved["services"]["core"].get("ports")
print("PASS: Compose runtime, tick progress, non-root mounts, network/capability isolation, replay")
