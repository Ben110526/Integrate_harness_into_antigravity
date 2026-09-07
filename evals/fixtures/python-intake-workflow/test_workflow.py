import unittest

from parser import parse_record
from service import intake_report
from store import import_batch


class IntakeTests(unittest.TestCase):
    def test_ac1_validated_parser(self):
        self.assertEqual(parse_record(" apple , 2 "), ("apple", 2))
        for record in ("", ",2", "apple,0", "apple,-1", "apple,two", "apple,1,2"):
            with self.subTest(record=record), self.assertRaises(ValueError):
                parse_record(record)

    def test_ac2_atomic_persistence(self):
        inventory = {"apple": 3}
        self.assertEqual(import_batch(["apple,2", "pear,1", "apple,4"], inventory), 7)
        self.assertEqual(inventory, {"apple": 9, "pear": 1})
        before = dict(inventory)
        with self.assertRaises(ValueError):
            import_batch(["apple,5", "pear,0"], inventory)
        self.assertEqual(inventory, before)
        self.assertEqual(import_batch([], inventory), 0)

    def test_ac3_integrated_report(self):
        inventory = {"pear": 4}
        self.assertEqual(
            intake_report(["apple,2", "pear,3"], inventory),
            {"imported_units": 5, "inventory": [("apple", 2), ("pear", 7)]},
        )
        self.assertEqual(inventory, {"apple": 2, "pear": 7})
        with self.assertRaises(ValueError):
            intake_report(["apple,9", "pear,-1"], inventory)
        self.assertEqual(inventory, {"apple": 2, "pear": 7})
        self.assertEqual(
            intake_report([], inventory),
            {"imported_units": 0, "inventory": [("apple", 2), ("pear", 7)]},
        )


if __name__ == "__main__":
    unittest.main()
