"""Public checks for the initial event waiting-list request."""
import unittest

from waiting_list import WaitingList


class WaitingListTests(unittest.TestCase):
    def test_join_returns_position_and_trims_names(self):
        waiting = WaitingList(2)
        self.assertEqual(waiting.join(" Mai "), 1)
        self.assertEqual(waiting.join("Lan"), 2)
        self.assertEqual(waiting.snapshot(), ["Mai", "Lan"])

    def test_initial_duplicate_rule_ignores_case_without_mutation(self):
        waiting = WaitingList(3)
        waiting.join("Mai")
        with self.assertRaises(ValueError):
            waiting.join(" mai ")
        self.assertEqual(waiting.snapshot(), ["Mai"])

    def test_full_list_is_unchanged_after_denied_join(self):
        waiting = WaitingList(1)
        waiting.join("Mai")
        with self.assertRaises(ValueError):
            waiting.join("Lan")
        self.assertEqual(waiting.snapshot(), ["Mai"])

    def test_snapshot_is_a_copy(self):
        waiting = WaitingList(2)
        waiting.join("Mai")
        waiting.snapshot().append("Lan")
        self.assertEqual(waiting.snapshot(), ["Mai"])


if __name__ == "__main__":
    unittest.main()
