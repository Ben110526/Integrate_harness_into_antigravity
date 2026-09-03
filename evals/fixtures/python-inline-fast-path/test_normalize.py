import unittest

from normalize import render_label


class NormalizeTests(unittest.TestCase):
    def test_collapses_internal_spaces(self) -> None:
        self.assertEqual(render_label("  alpha   beta  "), "[alpha beta]")


if __name__ == "__main__":
    unittest.main()
