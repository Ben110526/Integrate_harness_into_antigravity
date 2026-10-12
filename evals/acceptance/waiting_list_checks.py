#!/usr/bin/env python3
"""Runner-owned behavioral checks, deliberately outside the editable fixture."""
import importlib.util
import pathlib
import sys


def load_class(workspace):
    spec = importlib.util.spec_from_file_location("candidate_waiting_list", pathlib.Path(workspace) / "waiting_list.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.WaitingList


def raises_value_error(call):
    try:
        call()
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def check(criterion, WaitingList):
    if criterion == "AC-1":
        for invalid in (0, -1, True, 1.5, "2", None):
            raises_value_error(lambda: WaitingList(invalid))
        queue = WaitingList(2)
        assert queue.join("Mai") == 1
        assert queue.join("Lan") == 2
        raises_value_error(lambda: queue.join("An"))
        assert queue.snapshot() == ["Mai", "Lan"]
    elif criterion == "AC-2":
        queue = WaitingList(4)
        assert queue.join("  Mai  ") == 1
        assert queue.snapshot() == ["Mai"]
        for invalid in ("", "  ", 0, None, []):
            raises_value_error(lambda: queue.join(invalid))
            assert queue.snapshot() == ["Mai"]
    elif criterion == "AC-3":
        queue = WaitingList(4)
        queue.join("Mai")
        assert queue.join("mai") == 2
        raises_value_error(lambda: queue.join(" Mai "))
        assert queue.snapshot() == ["Mai", "mai"]
        assert queue.position("MAI") is None
        assert queue.cancel("MAI") is False
    elif criterion == "AC-4":
        queue = WaitingList(4)
        for name in ("Mai", "Lan", "An"):
            queue.join(name)
        assert queue.position(" Lan ") == 2
        assert queue.cancel(" Lan ") is True
        assert queue.cancel("missing") is False
        assert queue.position("An") == 2
        assert queue.position("Lan") is None
        assert queue.next() == "Mai"
        assert queue.next() == "An"
        assert queue.next() is None
    elif criterion == "AC-5":
        queue = WaitingList(2)
        queue.join("Mai"); queue.join("Lan")
        assert queue.cancel("Mai") is True
        assert queue.join("An") == 2
        assert queue.next() == "Lan"
        assert queue.join("Dao") == 2
        assert queue.snapshot() == ["An", "Dao"]
    elif criterion == "AC-6":
        queue = WaitingList(4)
        queue.join("Mai")
        assert queue.join_many([" Lan ", "An"]) == [2, 3]
        assert queue.snapshot() == ["Mai", "Lan", "An"]
        assert queue.join_many([]) == []
        assert queue.join_many(["mai"]) == [4]
    elif criterion == "AC-7":
        for batch in (["An", "Mai"], ["An", " An "], ["An", ""], ["An", None], ["An", "Dao", "Hoa"]):
            queue = WaitingList(3)
            queue.join("Mai")
            raises_value_error(lambda: queue.join_many(batch))
            assert queue.snapshot() == ["Mai"], "batch failure partially changed waiting names"
    elif criterion == "AC-8":
        queue = WaitingList(3); other = WaitingList(3)
        queue.join("Mai")
        snapshot = queue.snapshot(); snapshot.append("injected")
        assert queue.snapshot() == ["Mai"]
        assert other.snapshot() == []
    else:
        raise ValueError("unknown criterion")


if __name__ == "__main__":
    check(sys.argv[2], load_class(sys.argv[1]))
