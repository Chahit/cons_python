import unittest
import sys
from pathlib import Path

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[1]))
from ml_engine.base_loader_mixin import BaseLoaderMixin


class _DQHarness(BaseLoaderMixin):
    pass


class DataQualityTests(unittest.TestCase):
    def setUp(self):
        self.h = _DQHarness()

    def test_empty_frame_is_error(self):
        report = self.h._run_data_quality_checks(pd.DataFrame())
        self.assertEqual(report["status"], "error")
        self.assertTrue(any("empty" in e.lower() for e in report["errors"]))

    def test_duplicate_warning(self):
        df = pd.DataFrame(
            [
                {"company_name": "A", "group_name": "CPU", "total_spend": 10.0, "state": "X"},
                {"company_name": "A", "group_name": "CPU", "total_spend": 11.0, "state": "X"},
            ]
        )
        report = self.h._run_data_quality_checks(df)
        self.assertIn(report["status"], {"warn", "ok"})
        self.assertTrue(any("duplicate" in w.lower() for w in report["warnings"]))


if __name__ == "__main__":
    unittest.main()
