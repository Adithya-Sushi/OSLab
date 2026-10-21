import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "build" / platform.system()
MIB = 1024 * 1024

def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(path)

def read_text(path):
    try:
        return Path(path).read_text().strip()
    except (OSError, UnicodeError):
        return None

def source_manifest():
    files = {}
    for directory in ("src", "harness", "controller", "scripts", "tests"):
        for path in sorted((ROOT / directory).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                files[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    return {"sha256": digest, "files": files}

def boot_id():
    return read_text("/proc/sys/kernel/random/boot_id")

def host_information():
    return {"system": platform.system(), "release": platform.release(),
            "machine": platform.machine(), "python": platform.python_version(),
            "cpu_count": os.cpu_count(), "page_size": os.sysconf("SC_PAGESIZE"),
            "boot_id": boot_id(), "recorded_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

def command_version(command):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=5)
        return {"returncode": result.returncode, "stdout": result.stdout[:3000], "stderr": result.stderr[:1000]}
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"error": str(error)}
