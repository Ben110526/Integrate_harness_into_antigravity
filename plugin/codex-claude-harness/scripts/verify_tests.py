#!/usr/bin/env python3
"""Run native unittest and reject successful runs without executed tests.

Usage: python3 /absolute/path/verify_tests.py unittest [unittest arguments]

The exit status comes from unittest's result object, not parsed console output
or a caller-provided receipt. Expected failures retain unittest's normal success
semantics; unexpected successes fail. Other runners are intentionally unsupported.
"""

from __future__ import annotations

import os
import sys
from typing import List, Optional
import unittest


class CountedResult(unittest.TextTestResult):
    """Class/module skips must not subtract unrelated started test methods."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.skipped_started = 0
        self._active_test = False
        self._active_skipped = False

    def startTest(self, test):
        self._active_test = True
        self._active_skipped = False
        super().startTest(test)

    def addSkip(self, test, reason):
        if self._active_test and not self._active_skipped:
            self.skipped_started += 1
            self._active_skipped = True
        super().addSkip(test, reason)

    def stopTest(self, test):
        self._active_test = False
        super().stopTest(test)


class CountedRunner(unittest.TextTestRunner):
    resultclass = CountedResult


def main(arguments: Optional[List[str]] = None) -> int:
    args = list(sys.argv[1:] if arguments is None else arguments)
    if not args or args[0] != "unittest":
        print(
            "Usage: verify_tests.py unittest [unittest arguments] "
            "(only the native unittest runner is supported)",
            file=sys.stderr,
        )
        return 2

    # A script launched by absolute path otherwise lacks the cwd import entry
    # supplied by `python -m unittest`, so named project tests would not resolve.
    sys.path.insert(0, os.getcwd())
    try:
        program = unittest.TestProgram(
            module=None, argv=["unittest"] + args[1:], exit=False,
            testRunner=CountedRunner,
        )
    except SystemExit as error:
        # argparse exits successfully for --help, but that is not a test run.
        print("HARNESS_TEST_SUMMARY runner=unittest status=not-run", file=sys.stderr)
        return error.code if isinstance(error.code, int) and error.code else 2

    result = program.result
    skipped = len(result.skipped)
    # A method with skipped subtests is conservatively excluded, but class or
    # module fixture skips do not erase successful methods in other fixtures.
    executed = max(0, result.testsRun - result.skipped_started)
    successful = result.wasSuccessful()
    status = "failed" if not successful else "passed" if executed else "no-tests"
    print(
        "HARNESS_TEST_SUMMARY runner=unittest "
        f"tests_run={result.testsRun} skipped={skipped} executed={executed} "
        f"status={status}",
        file=sys.stderr,
    )
    if not successful:
        return 1
    return 0 if executed else 2


if __name__ == "__main__":
    sys.exit(main())
