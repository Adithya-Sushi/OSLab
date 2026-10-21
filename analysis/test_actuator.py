import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from harness.actuator import Actuator

class ActuatorProtocolTests(unittest.TestCase):
    def test_slow_reply_preserves_overdue_stop_and_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            executable=root/"reclaim_worker"
            executable.write_text("#!"+sys.executable+"\n"+
                "import sys,time,json\nfor line in sys.stdin:\n"
                " request,donor,amount=line.split(); start=time.monotonic(); time.sleep(.15)\n"
                " print(json.dumps(dict(request_id=int(request),start=start,end=time.monotonic(),wall_seconds=.15,cpu_seconds=.001,requested_bytes=int(amount),valid=True,errno=0,status='ok')),flush=True)\n")
            executable.chmod(0o755)
            with patch("harness.actuator.BIN",root):
                actuator=Actuator(root,root)
                try:
                    actuator.dispatch("A",33554432)
                    observation_ticks=0;reply=None;deadline=time.monotonic()+3
                    while time.monotonic()<deadline and reply is None:
                        observation_ticks+=1;reply=actuator.poll(.01);time.sleep(.01)
                    self.assertIsNotNone(reply)
                    self.assertGreater(observation_ticks,3)
                    self.assertTrue(actuator.overdue)
                    with self.assertRaises(RuntimeError):actuator.dispatch("B",33554432)
                    events=[json.loads(line) for line in (root/"reclaim_events.jsonl").read_text().splitlines()]
                    self.assertEqual([e["event"] for e in events],["dispatch","overdue","completion"])
                finally:
                    actuator.close()
                    actuator.process.stdout.close()

if __name__=="__main__":unittest.main()
