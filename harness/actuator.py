import json
from pathlib import Path
import queue
import subprocess
import threading
import time
from .common import BIN

class Actuator:
    def __init__(self, root, output, swappiness_max=False):
        self.log = (Path(output)/"reclaim_events.jsonl").open("w")
        self.stderr = (Path(output)/"actuator.stderr.log").open("w")
        command = [str(BIN/"reclaim_worker"),str(root)]
        if swappiness_max: command.append("--swappiness-max")
        self.process = subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                        stderr=self.stderr,text=True,bufsize=1)
        self.queue = queue.Queue(); self.current = None; self.overdue=False; self.sequence=0
        self.reader = threading.Thread(target=self.read,daemon=True); self.reader.start()

    def write(self,event):
        self.log.write(json.dumps(event)+"\n"); self.log.flush()

    def read(self):
        try:
            for line in self.process.stdout:
                self.queue.put(json.loads(line))
        except Exception as error: self.queue.put({"reader_error":repr(error)})

    def dispatch(self,donor,amount):
        if self.current or self.overdue: raise RuntimeError("one global request may be in flight; overdue stops dispatch")
        if donor not in ("A","B") or not isinstance(amount,int) or not 0<amount<=64*1024*1024:
            raise ValueError("invalid registered donor or request amount")
        if self.process.poll() is not None: raise RuntimeError("actuator exited")
        self.sequence += 1
        event = {"event":"dispatch","request_id":self.sequence,"donor":donor,
                 "requested_bytes":amount,"t":time.monotonic()}
        self.current = event; self.write(event)
        self.process.stdin.write(f"{self.sequence} {donor} {amount}\n"); self.process.stdin.flush()
        return event

    def poll(self,timeout_seconds=5):
        try: result=self.queue.get_nowait()
        except queue.Empty:
            if self.current and not self.overdue and time.monotonic()-self.current["t"]>timeout_seconds:
                self.overdue=True; self.write({"event":"overdue",**self.current,"event":"overdue"})
            return None
        if "reader_error" in result: raise RuntimeError(result["reader_error"])
        if not self.current or result["request_id"]!=self.current["request_id"]:
            raise RuntimeError("actuator reply ID mismatch")
        result = {**result,"event":"completion","donor":self.current["donor"],"dispatch_t":self.current["t"]}
        self.write(result); self.current=None
        return result

    def close(self):
        # A killed userspace process is not assumed to cancel kernel reclaim.
        if self.process.stdin: self.process.stdin.close()
        try: self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try: self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.write({"event":"unresolved_kernel_call","t":time.monotonic()})
        self.reader.join(timeout=1)
        self.log.close(); self.stderr.close()
