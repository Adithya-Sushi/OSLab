import copy
from pathlib import Path
import unittest
from .reference_effects import summarize

def fixture():
    records=[]
    for block in range(2):
        for arm,delta in (("none",5),("A",25),("B",10)):
            records.append({"directory":Path("unused-test-fixture"),
                "config":{"regime":"R1","block":block,"arm":arm,"donors":{"A":{"pattern":"structured"},"B":{"pattern":"random"}}},
                "outcome":{"status":"complete","attempt":f"fixture-{block}-{arm}","boot_id":f"fixture-boot-{block}-{arm}",
                           "delta_headroom_bytes":delta*1048576,"technical_invalidity":[],"adverse_outcomes":[]}})
    return records

class ReferenceTests(unittest.TestCase):
    def test_control_adjustment_and_source_contrast(self):
        result=summarize(fixture())
        self.assertEqual(result["regimes"]["R1"]["mean"],15)
        self.assertEqual(result["regimes"]["R1"]["gain_A"]["mean"],20)
        self.assertEqual(result["regimes"]["R1"]["gain_B"]["mean"],5)
        self.assertFalse(result["checkpoint_A_passed"])
    def test_adverse_outcome_is_retained(self):
        data=fixture();data[1]["outcome"]["adverse_outcomes"]=["timeout"]
        result=summarize(data)
        self.assertEqual(result["regimes"]["R1"]["n"],2)
        self.assertEqual(len(result["adverse_attempts"]),1)
    def test_technical_invalidity_keeps_visible_incomplete_block(self):
        data=fixture();data[1]["outcome"]["technical_invalidity"]=["generator_schedule_overloaded"]
        result=summarize(data)
        self.assertEqual(result["regimes"]["R1"]["n"],1)
        self.assertEqual(len(result["incomplete_blocks"]),1)
        self.assertEqual(len(result["technical_invalid_attempts"]),1)
    def test_duplicate_arms_and_shared_boot_rejected(self):
        data=fixture();data.append(copy.deepcopy(data[0]))
        with self.assertRaises(ValueError):summarize(data)
    def test_later_unseen_reuse_schedule_identifies_nonreusing_donor(self):
        data=fixture()
        for row in data:
            row["config"]["regime"]="R2"
            row["config"]["donors"]={"A":{"reuse-after":31},"B":{}}
        result=summarize(data)
        self.assertEqual(result["paired_effects"][0]["expected_better"],"B")
        self.assertEqual(result["regimes"]["R2"]["mean"],-15)
        data=fixture();data[1]["outcome"]["boot_id"]=data[0]["outcome"]["boot_id"]
        with self.assertRaises(ValueError):summarize(data)

if __name__=="__main__":unittest.main()
