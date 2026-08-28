import unittest

from calculator import divide


class DivideTests(unittest.TestCase):
    def test_divides_numbers(self) -> None:
        self.assertEqual(divide(8, 2), 4)

    def test_zero_denominator_has_domain_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "zero"):
            divide(8, 0)


if __name__ == "__main__":
    unittest.main()
