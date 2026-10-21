import errno
import json
from pathlib import Path
import platform
import subprocess
import tempfile
import time
import unittest
from harness.common import BIN
from harness.parsers import keyed,pressure,pressure_fraction,mm_stat,swap_devices
from harness.load_generator import ScheduledClient,expected_result
from harness.launch import Worker
from analysis.statistics import mean_window,bootstrap_mean,wilson
from controller.budget import Budget
from controller.estimator import LastProbeEstimator,Evidence
from controller.policies import Policy

class CounterTests(unittest.TestCase):
    def test_key_order_and_optional_absence(self):
        values=keyed("file 20\nanon 50\nnew_counter 9\n")
        self.assertEqual(values["anon"],50)
        self.assertIsNone(values.get("workingset_refault_anon"))
        self.assertIsNone(keyed(None))
    def test_meminfo_units(self):self.assertEqual(keyed("MemAvailable: 42 kB")["MemAvailable"],43008)
    def test_zram_footprint_includes_allocator(self):
        parsed=mm_stat("100 30 48 0 50 1 2")
        self.assertEqual(parsed["mem_used_total"],48)
        self.assertIsNone(parsed["huge_pages"])
    def test_zram_future_fields_retained(self):self.assertEqual(mm_stat("1 2 3 4 5 6 7 8 9 10")["extra_fields"],[10])
    def test_invalid_zram_layout(self):
        with self.assertRaises(ValueError):mm_stat("1 2 3")
    def test_pressure_total_uses_actual_elapsed(self):
        self.assertEqual(pressure("some avg10=0.0 total=90")["some"]["total"],90)
        self.assertAlmostEqual(pressure_fraction(0,100000,2),.05)
        self.assertIsNone(pressure_fraction(100,1,2))
        self.assertIsNone(pressure_fraction(None,1,2))
    def test_swap_devices(self):self.assertEqual(swap_devices("Filename Type Size Used Priority\n/dev/zram0 partition 1024 1 100")[0]["size_bytes"],1048576)

class AnalysisTests(unittest.TestCase):
    def test_irregular_time_weighting(self):
        points=[{"t":0,"headroom_bytes":0},{"t":1,"headroom_bytes":10},{"t":4,"headroom_bytes":40}]
        self.assertAlmostEqual(mean_window(points,.5,3.5),20)
    def test_missing_coverage_rejected(self):
        with self.assertRaises(ValueError):mean_window([{"t":1,"headroom_bytes":3},{"t":2,"headroom_bytes":3}],0,2)
    def test_bootstrap_runs(self):
        result=bootstrap_mean([4,4,4]);self.assertEqual(result["ci95"],[4,4]);self.assertEqual(result["n"],3)
    def test_rank_interval_small_sample(self):self.assertLess(wilson(8,8)[0],.8)

class ControllerTests(unittest.TestCase):
    def test_budget_charges_probes_and_blocks_overlap(self):
        budget=Budget(byte_cap=64,wall_cap=1)
        self.assertTrue(budget.admit(32));self.assertFalse(budget.admit(32))
        budget.complete({"wall_seconds":.1,"cpu_seconds":.01})
        self.assertTrue(budget.admit(32));budget.complete({"wall_seconds":.1,"cpu_seconds":.01})
        self.assertFalse(budget.admit(32));self.assertEqual(budget.requested,64)
    def test_time_overshoot_stops_later_work(self):
        budget=Budget(wall_cap=.1);budget.admit(32);budget.complete({"wall_seconds":.3,"cpu_seconds":.02})
        self.assertFalse(budget.admit(32));self.assertAlmostEqual(budget.snapshot()["wall_overshoot"],.2)
    def test_overdue_never_admits_another(self):
        budget=Budget();budget.admit(32);budget.overdue();self.assertFalse(budget.admit(32))
    def test_missing_stale_and_future_evidence_abstain(self):
        estimator=LastProbeEstimator(stale_seconds=10)
        self.assertEqual(estimator.predict("A",1)["status"],"UNKNOWN")
        estimator.history["A"]=Evidence("A",10,10,10,1,.1,False)
        self.assertEqual(estimator.predict("A",9)["status"],"UNKNOWN")
        self.assertEqual(estimator.predict("A",21)["status"],"UNKNOWN")
    def test_interference_abstains(self):
        estimator=LastProbeEstimator();estimator.history["A"]=Evidence("A",0,10,10,1,.1,True)
        self.assertEqual(estimator.predict("A",1)["reason"],"interference")
    def test_ineligible_donor_cannot_be_probed(self):
        policy=Policy("delayed",LastProbeEstimator())
        self.assertIsNone(policy.choose(1,{}, {"A":False,"B":False})[0])
        self.assertEqual(policy.choose(1,{}, {"A":False,"B":True})[0],"B")
    def test_ranking_uses_delayed_conservative_gain_per_cost(self):
        estimator=LastProbeEstimator()
        estimator.history={"A":Evidence("A",10,100,1000,1,1,False),"B":Evidence("B",10,80,10,1,.1,False)}
        self.assertEqual(Policy("delayed",estimator).choose(11,{}, {"A":True,"B":True})[0],"B")
        self.assertEqual(Policy("immediate",estimator).choose(11,{}, {"A":True,"B":True})[0],"A")

@unittest.skipUnless((BIN/"donor").exists(),"compile C workloads first")
class WorkloadTests(unittest.TestCase):
    def test_donor_content_and_reuse_preserve_checksum(self):
        checksums=[]
        for _ in range(2):
            result=subprocess.run([str(BIN/"donor"),"--mib","4","--hot-mib","1","--reuse-mib","4",
                                   "--reuse-after","0.1","--duration","0.3","--seed","17"],capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)
            events=[json.loads(line) for line in result.stdout.splitlines()]
            self.assertTrue(any(e["event"]=="phase" for e in events))
            self.assertTrue(events[-1]["ok"]);checksums.append(events[0]["checksum"])
        self.assertEqual(checksums[0],checksums[1])
    def test_invalid_memory_size_rejected(self):
        result=subprocess.run([str(BIN/"donor"),"--mib","0"],capture_output=True,timeout=3)
        self.assertEqual(result.returncode,2)
    def test_foreground_scheduled_requests_validate(self):
        with tempfile.TemporaryDirectory() as directory:
            endpoint=Path(tempfile.gettempdir())/f"oslab-test-{time.time_ns()}.sock"
            worker=Worker("foreground-test",[str(BIN/"foreground"),"--socket",str(endpoint),"--mib","4","--touches","64"],directory)
            try:
                worker.await_ready()
                client=ScheduledClient(endpoint,Path(directory)/"requests.csv",100,.3,4,64)
                client.start();self.assertTrue(client.ready.wait(3));client.start_at(time.monotonic()+.05);client.join(5)
                self.assertIsNone(client.error);self.assertEqual(client.summary()["offered"],30)
                self.assertEqual(client.summary()["failed_or_missed"],0)
                for row in client.records:self.assertGreaterEqual(row["latency_seconds"],row["completion"]-row["actual_send"])
            finally:worker.stop()
    def test_non_cgroup_actuator_target_rejected(self):
        result=subprocess.run([str(BIN/"reclaim_worker"),tempfile.gettempdir()],input="1 A 33554432\n",capture_output=True,text=True,timeout=3)
        self.assertEqual(result.returncode,2)
    @unittest.skipUnless(platform.system()=="Linux","Linux actuator protocol")
    def test_actuator_rejects_invalid_and_duplicate_ids(self):
        # /sys/fs/cgroup/A is absent in the dedicated guest: no real donor is touched.
        if Path("/sys/fs/cgroup/A").exists():self.skipTest("test requires absent root A leaf")
        data="0 A 33554432\n1 ../A 33554432\n2 A -1\n3 A 33554432\n3 A 33554432\n4 B 1\n"
        result=subprocess.run([str(BIN/"reclaim_worker"),"/sys/fs/cgroup"],input=data,capture_output=True,text=True,timeout=3)
        self.assertEqual(result.returncode,0,result.stderr)
        rows=[json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(rows),6)
        self.assertEqual(rows[3]["errno"],errno.ENOENT)
        self.assertEqual([r["valid"] for r in rows],[False,False,False,True,False,False])

if __name__=="__main__":unittest.main()
