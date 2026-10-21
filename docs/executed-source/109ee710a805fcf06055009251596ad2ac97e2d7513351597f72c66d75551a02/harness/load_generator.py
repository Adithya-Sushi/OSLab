import asyncio
import csv
from pathlib import Path
import threading
import time

MASK = (1 << 64)-1
SALT = 0x517cc1b727220a95

def expected_result(key, mib, touches):
    words = mib*1024*1024//8
    return sum((((key+j*4099) % words) ^ SALT) ^ key for j in range(touches)) & MASK

def percentile(values, fraction):
    if not values: return None
    values = sorted(values)
    position = (len(values)-1)*fraction
    low = int(position); high = min(low+1,len(values)-1)
    return values[low]+(values[high]-values[low])*(position-low)

class ScheduledClient(threading.Thread):
    def __init__(self, socket, output, rate, duration, mib, touches, max_outstanding=64, timeout=2):
        super().__init__(daemon=True)
        self.socket, self.output = str(socket), Path(output)
        self.rate, self.duration, self.mib, self.touches = rate,duration,mib,touches
        self.max_outstanding, self.timeout = max_outstanding, timeout
        self.records, self.error = [], None
        self.ready, self.go = threading.Event(), threading.Event()
        self.epoch = None

    def start_at(self, epoch):
        self.epoch = epoch; self.go.set()

    def run(self):
        try:
            count = int(self.rate*self.duration)
            cache = {i: expected_result((i+1)*7919, self.mib, self.touches) for i in range(min(256,count))}
            expected = [cache[i%256] for i in range(count)]
            self.ready.set(); self.go.wait()
            asyncio.run(self.generate(expected))
        except Exception as error:
            self.error = repr(error); self.ready.set()

    async def generate(self, expected):
        fields = ["id","scheduled","generated","actual_send","completion","latency_seconds","generator_lateness_seconds","status","correct"]
        with self.output.open("w", newline="") as stream:
            writer = csv.DictWriter(stream,fieldnames=fields); writer.writeheader()
            def record(row):
                self.records.append(row); writer.writerow(row); stream.flush()
            async def request(i, scheduled, generated):
                row = {"id": i, "scheduled": scheduled, "generated": generated,
                       "generator_lateness_seconds": max(0,generated-scheduled), "actual_send": None,
                       "completion": None, "latency_seconds": None, "status": "failed", "correct": False}
                connection = None
                try:
                    async with asyncio.timeout(self.timeout):
                        reader, connection = await asyncio.open_unix_connection(self.socket)
                        connection.write(f"{i} {(i%256+1)*7919}\n".encode()); await connection.drain()
                        row["actual_send"] = time.monotonic()
                        reply = await reader.readline(); complete = time.monotonic()
                        reply_id,result = map(int,reply.split())
                        row.update(completion=complete,latency_seconds=complete-scheduled,
                                   correct=reply_id==i and result==expected[i])
                        row["status"] = "ok" if row["correct"] else "incorrect"
                except (OSError, ValueError, asyncio.TimeoutError) as error:
                    row.update(completion=time.monotonic(),status="timeout" if isinstance(error,TimeoutError) else "failed")
                    row["latency_seconds"] = row["completion"]-scheduled
                finally:
                    if connection:
                        connection.close()
                        try: await connection.wait_closed()
                        except OSError: pass
                    record(row)
            active = set()
            for i in range(len(expected)):
                scheduled = self.epoch+i/self.rate
                await asyncio.sleep(max(0,scheduled-time.monotonic()))
                generated = time.monotonic()
                if len(active) >= self.max_outstanding:
                    record({"id":i,"scheduled":scheduled,"generated":generated,"actual_send":None,
                            "completion":None,"latency_seconds":None,"generator_lateness_seconds":max(0,generated-scheduled),
                            "status":"missed","correct":False})
                else:
                    task = asyncio.create_task(request(i,scheduled,generated))
                    active.add(task); task.add_done_callback(active.discard)
            if active: await asyncio.gather(*active)

    def summary(self, start=None, end=None):
        rows = [row for row in self.records if (start is None or row["scheduled"]>=start) and
                (end is None or row["scheduled"]<end)]
        good = [row["latency_seconds"] for row in rows if row["status"]=="ok"]
        return {"offered":len(rows), "completed":len(good), "failed_or_missed":len(rows)-len(good),
                "p50_seconds":percentile(good,.5), "p99_seconds":percentile(good,.99),
                "max_generator_lateness_seconds":max((row["generator_lateness_seconds"] for row in rows),default=None)}
