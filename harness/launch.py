import json
from pathlib import Path
import subprocess
import sys
import threading
import time
from .common import ROOT

class Worker:
    def __init__(self, name, command, directory, group=None):
        self.name, self.events, self.ready = name, [], threading.Event()
        self.error = None
        self.stdout = (Path(directory)/(name+".stdout.log")).open("w")
        self.stderr = (Path(directory)/(name+".stderr.log")).open("w")
        if group:
            command = [sys.executable, "-m", "harness.exec_in_group", str(group), *map(str,command)]
        self.process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=self.stderr, text=True, bufsize=1, start_new_session=True)
        self.reader = threading.Thread(target=self.read, daemon=True); self.reader.start()

    def read(self):
        for line in self.process.stdout:
            self.stdout.write(line); self.stdout.flush()
            try:
                event = json.loads(line)
                self.events.append({"worker": self.name, **event})
                if event.get("event") == "ready": self.ready.set()
            except json.JSONDecodeError:
                self.error = "non-JSON worker output"

    def await_ready(self, timeout=60):
        deadline = time.monotonic()+timeout
        while time.monotonic()<deadline:
            if self.ready.wait(0.1): return
            if self.process.poll() is not None: break
        raise RuntimeError(f"{self.name} failed to become ready; returncode={self.process.poll()}")

    def start_at(self, epoch):
        self.process.stdin.write(f"START {epoch:.9f}\n"); self.process.stdin.flush()

    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.process.kill(); self.process.wait(timeout=5)
            self.error = "worker required SIGKILL"
        self.reader.join(timeout=3)
        self.stdout.close(); self.stderr.close()
        if self.process.stdin: self.process.stdin.close()
        if self.process.stdout: self.process.stdout.close()

def prepare_groups(parent, run_name, foreground_mib, donor_mib):
    parent = Path(parent)
    if "memory" not in (parent/"cgroup.subtree_control").read_text().split():
        raise RuntimeError("parent must have an enabled, delegated memory controller")
    trial = parent/run_name
    trial.mkdir()
    try:
        (trial/"cgroup.subtree_control").write_text("+memory +cpu")
        groups = {}
        for name in ("foreground", "A", "B", "interference"):
            leaf = trial/name; leaf.mkdir(); groups[name] = leaf
            (leaf/"memory.oom.group").write_text("1")
            (leaf/"memory.max").write_text(str((foreground_mib+256 if name=="foreground" else donor_mib+256)*1024*1024))
        # Protection is held identical across all arms. No hard latency guarantee is inferred.
        return trial, groups
    except Exception:
        for leaf in trial.iterdir():
            if leaf.is_dir(): leaf.rmdir()
        trial.rmdir()
        raise

def remove_groups(trial, groups):
    for group in groups.values():
        if (group/"cgroup.procs").read_text().strip():
            raise RuntimeError(f"live workers remain in {group}")
        group.rmdir()
    trial.rmdir()
