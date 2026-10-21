import csv
import json
from pathlib import Path
import resource
import threading
import time
from .common import read_text
from .parsers import keyed, mm_stat, pressure, MM_STAT_FIELDS

class Collector(threading.Thread):
    def __init__(self, output, groups, interval=0.25):
        super().__init__(daemon=True)
        self.output, self.groups, self.interval = Path(output), groups, interval
        self.stop_event = threading.Event()
        self.samples, self.error = [], None

    def run(self):
        try:
            self.collect()
        except Exception as error:
            self.error = repr(error)

    def collect(self):
        with (self.output/"raw_counters.jsonl").open("w") as raw, (self.output/"telemetry.csv").open("w", newline="") as parsed:
            writer = csv.DictWriter(parsed, fieldnames=["t", "scan_end", "headroom_bytes", "free_bytes", "swap_free_bytes", "zram_alloc_bytes", "observer_cpu_seconds", "observer_maxrss"])
            writer.writeheader()
            deadline = time.monotonic()
            while not self.stop_event.is_set():
                start = time.monotonic()
                originals = {"meminfo": read_text("/proc/meminfo"), "vmstat": read_text("/proc/vmstat"),
                             "stat": read_text("/proc/stat"), "pressure_memory": read_text("/proc/pressure/memory"),
                             "pressure_cpu": read_text("/proc/pressure/cpu"), "groups": {}, "zram": {}}
                for name, group in self.groups.items():
                    originals["groups"][name] = {key: read_text(Path(group)/key) for key in
                        ("memory.current", "memory.swap.current", "memory.stat", "memory.pressure", "memory.events", "memory.events.local", "cpu.stat")}
                for device in sorted(Path("/sys/block").glob("zram*")):
                    originals["zram"][device.name] = {key: read_text(device/key) for key in ("mm_stat", "io_stat", "bd_stat")}
                memory = keyed(originals["meminfo"]) or {}
                pools = {name: mm_stat(value["mm_stat"]) for name, value in originals["zram"].items()}
                allocations = [pool["mem_used_total"] for pool in pools.values() if pool]
                usage = resource.getrusage(resource.RUSAGE_SELF)
                sample = {"t": start, "scan_end": time.monotonic(),
                          "headroom_bytes": memory.get("MemAvailable"), "free_bytes": memory.get("MemFree"),
                          "swap_free_bytes": memory.get("SwapFree"),
                          "zram_alloc_bytes": sum(allocations) if allocations else None,
                          "observer_cpu_seconds": usage.ru_utime+usage.ru_stime,
                          "observer_maxrss": usage.ru_maxrss}
                raw.write(json.dumps({"t": start, "scan_end": sample["scan_end"], "raw": originals,
                                      "zram_field_map": list(MM_STAT_FIELDS)})+"\n")
                writer.writerow(sample)
                raw.flush(); parsed.flush()
                # Only live counters are available to the policy; raw workload labels are elsewhere.
                live_groups = {}
                for name, value in originals["groups"].items():
                    live_groups[name] = {"stat": keyed(value["memory.stat"]), "pressure": pressure(value["memory.pressure"]),
                                         "events": keyed(value["memory.events"]), "cpu": keyed(value["cpu.stat"])}
                self.samples.append({**sample, "groups": live_groups})
                deadline += self.interval
                if deadline < time.monotonic(): deadline = time.monotonic()+self.interval
                self.stop_event.wait(max(0,deadline-time.monotonic()))

    def stop(self):
        self.stop_event.set(); self.join(timeout=5)
