import unittest
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
from frontend.tabs.market_basket import _generate_human_script


class TestBundleScript(unittest.TestCase):
    def test_generate_human_script_long_days(self):
        # Days since last > 60
        script = _generate_human_script(
            partner_name="Alpha Corp",
            trigger_product="Product A",
            rec_product="Product B",
            trigger_category="Hardware",
            rec_category="Hardware",
            confidence=0.75,
            lift=3.5,
            frequency=25,
            gain_monthly=150000,
            days_since_last=75,
            partner_order_count=10,
        )
        self.assertIn("opening", script)
        self.assertIn("pitch", script)
        self.assertIn("value", script)
        self.assertIn("objection", script)
        self.assertIn("close", script)
        self.assertTrue(any("75 days" in str(v) or "days since" in str(v) for v in script.values()))

    def test_generate_human_script_high_confidence(self):
        script = _generate_human_script(
            partner_name="Beta Inc",
            trigger_product="Product X",
            rec_product="Product Y",
            trigger_category="Software",
            rec_category="Software",
            confidence=0.85,
            lift=4.0,
            frequency=50,
            gain_monthly=50000,
            days_since_last=15,
            partner_order_count=30,
        )
        self.assertIn("opening", script)
        self.assertIn("pitch", script)
        self.assertIn("value", script)
        self.assertIn("objection", script)
        self.assertIn("close", script)
        self.assertTrue(any("85%" in str(v) or "confidence" in str(v).lower() or "reliable" in str(v) for v in script.values()))


if __name__ == "__main__":
    unittest.main()
