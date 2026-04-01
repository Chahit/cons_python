import unittest
import sys
from pathlib import Path

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[1]))
from ml_engine.associations_mixin import AssociationsMixin


class AssociationRuleTests(unittest.TestCase):
    def test_rule_strength_decoration(self):
        df = pd.DataFrame(
            [
                {"support_a": 10, "support_b": 10, "confidence_a_to_b": 0.5, "lift_a_to_b": 2.0},
                {"support_a": 10, "support_b": 10, "confidence_a_to_b": 0.25, "lift_a_to_b": 1.2},
                {"support_a": 10, "support_b": 10, "confidence_a_to_b": 0.1, "lift_a_to_b": 1.0},
            ]
        )
        out = AssociationsMixin._decorate_rule_quality(
            df.copy(), min_support=5, include_low_support=True
        )
        self.assertEqual(out.iloc[0]["rule_strength"], "High")
        self.assertEqual(out.iloc[1]["rule_strength"], "Medium")
        self.assertEqual(out.iloc[2]["rule_strength"], "Low")

    def test_low_support_filter(self):
        df = pd.DataFrame(
            [
                {"support_a": 2, "support_b": 9, "confidence_a_to_b": 0.5, "lift_a_to_b": 2.0},
                {"support_a": 7, "support_b": 8, "confidence_a_to_b": 0.5, "lift_a_to_b": 2.0},
            ]
        )
        out = AssociationsMixin._decorate_rule_quality(
            df.copy(), min_support=5, include_low_support=False
        )
        self.assertEqual(len(out), 1)
        self.assertTrue(bool(out.iloc[0]["low_support_flag"]) is False)


if __name__ == "__main__":
    unittest.main()
