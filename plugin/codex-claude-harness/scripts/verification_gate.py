#!/usr/bin/env python3
"""Bounded Stop hook that requires post-write verification evidence.

The hook records only step numbers and a short evidence label in the
conversation artifact directory. It never executes project checks itself.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import shlex
import stat
import sys
import tempfile
import time
from contextlib import contextmanager
from typing import Any, Iterator, Optional
from urllib.parse import unquote, urlparse


STATE_FILE = ".codex-claude-harness-verification.json"
TEMP_STATE_PREFIX = "codex-claude-harness-"
TEMP_STATE_DIRECTORY_PREFIX = "codex-claude-harness-state-"
TEMP_STATE_TTL_SECONDS = 48 * 60 * 60
STATE_LOCK_TIMEOUT_SECONDS = 5.0
STATE_LOCK_POLL_SECONDS = 0.05
WRITE_TOOLS = {
    "write_to_file",
    "replace_file_content",
    "multi_replace_file_content",
}
MAX_GATE_RETRIES = 1
NO_CHECK_MARKER = "HARNESS_NO_RUNNABLE_CHECK:"
EVIDENCE = "evidence"
MUTATION = "mutation"
NEUTRAL = "neutral"
WAIVER = "waiver"

_SCRIPT_EVIDENCE_NAME = re.compile(
    r"(?:^|[-_.])(?:test|tests|check|lint|verify|validate|doctor|build)(?:[-_.]|$)",
    re.IGNORECASE,
)
_SCRIPT_MUTATION_NAME = re.compile(
    r"(?:^|[-_.])(?:format|fix|generate|codegen)(?:[-_.]|$)",
    re.IGNORECASE,
)
_TEMP_STATE_NAME = re.compile(
    rf"^{re.escape(TEMP_STATE_PREFIX)}[0-9a-f]{{24}}\.json$"
)


def _emit(value: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(value, separators=(",", ":")) + "\n")


def _read_payload() -> dict[str, Any]:
    payload = json.load(sys.stdin)
    if not isinstance(payload, dict):
        raise ValueError("hook payload must be an object")
    return payload


def _state_path(payload: dict[str, Any]) -> Path:
    artifact_dir = payload.get("artifactDirectoryPath")
    if isinstance(artifact_dir, str) and artifact_dir.strip():
        return Path(artifact_dir).expanduser().resolve(strict=False) / STATE_FILE

    conversation_id = str(payload.get("conversationId", "unknown"))
    digest = hashlib.sha256(conversation_id.encode("utf-8", "replace")).hexdigest()[:24]
    directory = _private_state_directory()
    if directory is None:
        raise OSError("private verification state directory is unavailable")
    return directory / f"{TEMP_STATE_PREFIX}{digest}.json"


def _private_state_directory(temp_root: Optional[Path] = None) -> Optional[Path]:
    base = temp_root or Path(tempfile.gettempdir())
    identity = (
        str(os.getuid())
        if hasattr(os, "getuid")
        else hashlib.sha256(
            (os.environ.get("USERNAME", "user") + str(Path.home())).encode(
                "utf-8", "replace"
            )
        ).hexdigest()[:16]
    )
    directory = base / (TEMP_STATE_DIRECTORY_PREFIX + identity)
    try:
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            pass
        if os.name == "nt":
            metadata = directory.lstat()
            if not stat.S_ISDIR(metadata.st_mode) or directory.is_symlink():
                return None
        else:
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(str(directory), flags)
            try:
                metadata = os.fstat(descriptor)
                if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid():
                    return None
                os.fchmod(descriptor, 0o700)
                metadata = os.fstat(descriptor)
                current = directory.lstat()
                if (
                    not stat.S_ISDIR(current.st_mode)
                    or metadata.st_dev != current.st_dev
                    or metadata.st_ino != current.st_ino
                    or metadata.st_mode & (stat.S_IRWXG | stat.S_IRWXO)
                ):
                    return None
            finally:
                os.close(descriptor)
        return directory
    except OSError:
        return None


def _open_regular_file(path: Path, flags: int, mode: int = 0o600) -> Any:
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if path.is_symlink():
        raise OSError("state path must not be a symlink")
    descriptor = os.open(str(path), flags, mode)
    try:
        metadata = os.fstat(descriptor)
        current = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise OSError("state path must be a regular single-link file")
        if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
            raise OSError("state file must be owned by the current user")
        if metadata.st_dev != current.st_dev or metadata.st_ino != current.st_ino:
            raise OSError("state path changed while opening")
        if flags & (os.O_WRONLY | os.O_RDWR) and os.name != "nt":
            os.fchmod(descriptor, mode)
        return os.fdopen(descriptor, "r+b" if flags & os.O_RDWR else "rb", buffering=0)
    except Exception:
        os.close(descriptor)
        raise


def _open_file_matches_path(handle: Any, path: Path) -> bool:
    try:
        opened = os.fstat(handle.fileno())
        current = path.lstat()
    except OSError:
        return False
    return (
        stat.S_ISREG(current.st_mode)
        and opened.st_dev == current.st_dev
        and opened.st_ino == current.st_ino
    )


@contextmanager
def _state_lock(path: Path, blocking: bool = True) -> Iterator[bool]:
    """Hold a cross-process lock for one state file.

    The lock lives in a separate stable file because `_save_state` atomically
    replaces the state inode. Keeping the lock outside that inode makes the
    complete load/merge/save transaction safe on both POSIX and Windows.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        yield False
        return
    # Fallback states share one temp-directory lock. This avoids creating one
    # orphan lock file per conversation while still serializing their tiny
    # read/merge/write transactions. Artifact-local locks disappear with the
    # artifact directory's normal lifecycle.
    if _TEMP_STATE_NAME.fullmatch(path.name):
        lock_path = path.parent / ".codex-claude-harness-verification.lock"
    else:
        lock_path = path.with_name(f"{path.name}.lock")
    try:
        handle = _open_regular_file(lock_path, os.O_RDWR | os.O_CREAT)
    except OSError:
        yield False
        return
    acquired = False
    try:
        if os.name == "nt":
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()

        deadline = time.monotonic() + STATE_LOCK_TIMEOUT_SECONDS
        while not acquired:
            try:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except (BlockingIOError, OSError):
                if not blocking or time.monotonic() >= deadline:
                    break
                time.sleep(STATE_LOCK_POLL_SECONDS)

        if acquired and not _open_file_matches_path(handle, lock_path):
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            acquired = False
        yield acquired
    finally:
        if acquired:
            try:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        handle.close()


def _cleanup_stale_temp_states(
    temp_dir: Optional[Path] = None,
    now: Optional[float] = None,
) -> None:
    """Best-effort cleanup for inactive fallback states older than 48 hours."""
    directory = temp_dir or _private_state_directory()
    if directory is None:
        return
    cutoff = (time.time() if now is None else now) - TEMP_STATE_TTL_SECONDS
    try:
        candidates = itertools.islice(
            directory.glob(f"{TEMP_STATE_PREFIX}*.json"),
            256,
        )
    except OSError:
        return

    for candidate in candidates:
        if not _TEMP_STATE_NAME.fullmatch(candidate.name):
            continue
        try:
            metadata = candidate.lstat()
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_mtime >= cutoff:
                continue
        except OSError:
            continue
        # Never remove state that another hook process is updating. Recheck its
        # age after obtaining the lock in case a writer refreshed it meanwhile.
        with _state_lock(candidate, blocking=False) as acquired:
            if not acquired:
                continue
            try:
                metadata = candidate.lstat()
                if stat.S_ISREG(metadata.st_mode) and metadata.st_mtime < cutoff:
                    candidate.unlink()
            except (FileNotFoundError, OSError):
                pass


def _cleanup_fallback_states(payload: dict[str, Any]) -> None:
    artifact_dir = payload.get("artifactDirectoryPath")
    if isinstance(artifact_dir, str) and artifact_dir.strip():
        return
    # Some hook payloads omit conversationId, so their state path always hashes
    # the literal "unknown" and cannot identify a new session by path existence.
    # Age-check every fallback invocation; the bounded glob and nonblocking lock
    # make this safe while ensuring an old unknown state cannot leak forward.
    _cleanup_stale_temp_states()


def _load_state(path: Path) -> dict[str, Any]:
    try:
        with _open_regular_file(path, os.O_RDONLY) as handle:
            state = json.loads(handle.read().decode("utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return state if isinstance(state, dict) else {}


def _save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary = Path(temporary_name)
    try:
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            handle.write(json.dumps(state, sort_keys=True, separators=(",", ":")))
            handle.flush()
        os.replace(str(temporary), str(path))
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _tool_call(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    tool_call = payload.get("toolCall")
    if not isinstance(tool_call, dict):
        return "", {}
    name = tool_call.get("name")
    args = tool_call.get("args")
    return (
        name if isinstance(name, str) else "",
        args if isinstance(args, dict) else {},
    )


def _step(payload: dict[str, Any]) -> int:
    value = payload.get("stepIdx")
    return value if isinstance(value, int) and not isinstance(value, bool) else -1


def _as_local_path(value: str) -> Path:
    if value.startswith("file://"):
        parsed = urlparse(value)
        value = unquote(parsed.path)
    return Path(value).expanduser()


def _is_within(candidate: Path, root: Path) -> bool:
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except (OSError, ValueError):
        return False


def _is_workspace_write(args: dict[str, Any], payload: dict[str, Any]) -> bool:
    if args.get("IsArtifact") is True:
        return False

    target = args.get("TargetFile")
    if not isinstance(target, str) or not target.strip():
        return False

    roots = [
        _as_local_path(root)
        for root in payload.get("workspacePaths", [])
        if isinstance(root, str) and root.strip()
    ]
    if not roots:
        return True

    candidate = _as_local_path(target)
    if not candidate.is_absolute():
        candidate = roots[0] / candidate
    return any(_is_within(candidate, root) for root in roots)


def _command(args: dict[str, Any]) -> str:
    for key in ("CommandLine", "command", "Command"):
        value = args.get(key)
        if isinstance(value, str):
            return value.strip()
    return ""


def _waiver_reason(command: str) -> str:
    marker_index = command.find(NO_CHECK_MARKER)
    if marker_index < 0:
        return ""
    reason = command[marker_index + len(NO_CHECK_MARKER) :]
    reason = re.split(r"[\r\n;&|]", reason, maxsplit=1)[0]
    reason = reason.strip(" \t'\"`)")
    if len(reason) < 12:
        return ""
    if reason.casefold() in {"no tests", "none available", "not applicable"}:
        return ""
    return reason[:300]


def _tokens(command: str) -> tuple[list[list[str]], bool]:
    """Return command segments and whether shell semantics can mask failure.

    Only `&&` is treated as an ordered, success-preserving separator. Pipes,
    OR, semicolons, backgrounding, and newlines make verification evidence
    unsafe, though mutations inside them are still tracked conservatively.
    """
    if not command:
        return [], False
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>")
        lexer.whitespace_split = True
        lexer.commenters = ""
        if os.name == "nt":
            # PowerShell/cmd paths commonly contain unquoted backslashes. In
            # POSIX shlex mode they are escapes unless explicitly disabled.
            lexer.escape = ""
        values = list(lexer)
    except ValueError:
        return [], True

    segments: list[list[str]] = [[]]
    unsafe = "\n" in command or "\r" in command
    for value in values:
        if value == "&&":
            segments.append([])
        elif value in {"||", "|", ";", "&"} or (
            value and set(value) <= {";", "|"}
        ):
            unsafe = True
            segments.append([])
        else:
            segments[-1].append(value)
    return [segment for segment in segments if segment], unsafe


def _executable(value: str) -> str:
    name = value.replace("\\", "/").rsplit("/", 1)[-1].casefold()
    for suffix in (".exe", ".cmd", ".bat"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name


def _strip_prefixes(values: list[str]) -> list[str]:
    values = list(values)
    while values and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", values[0]):
        values.pop(0)
    while values:
        executable = _executable(values[0])
        if executable == "env":
            values.pop(0)
            while values and (values[0].startswith("-") or "=" in values[0]):
                values.pop(0)
        elif executable in {"command", "time"}:
            values.pop(0)
        else:
            break
    return values


def _script_name_is_evidence(value: str) -> bool:
    name = value.replace("\\", "/").rsplit("/", 1)[-1]
    stem, dot, extension = name.rpartition(".")
    if not dot or extension.casefold() not in {"sh", "py", "ps1", "cmd", "bat"}:
        return False
    return bool(_SCRIPT_EVIDENCE_NAME.search(stem))


def _script_name_is_mutation(value: str) -> bool:
    name = value.replace("\\", "/").rsplit("/", 1)[-1]
    stem, dot, extension = name.rpartition(".")
    if not dot or extension.casefold() not in {"sh", "py", "ps1", "cmd", "bat"}:
        return False
    return bool(_SCRIPT_MUTATION_NAME.search(stem))


def _named(value: str, names: set[str]) -> bool:
    value = value.casefold()
    return any(value == name or value.startswith(f"{name}:") for name in names)


def _has_flag(values: list[str], flags: set[str]) -> bool:
    return any(value.casefold() in flags for value in values)


def _classify_coverage_run(args: list[str], depth: int) -> str:
    """Recognize coverage only when it wraps a known verification target."""
    lowered = [value.casefold() for value in args]
    if lowered[:1] != ["run"]:
        return NEUTRAL

    run_args = args[1:]
    options_with_values = {
        "--concurrency", "--context", "--data-file", "--debug", "--include",
        "--omit", "--rcfile", "--save-signal", "--source",
    }
    flag_options = {
        "-a", "--append", "--branch", "-l", "--pylib", "-p",
        "--parallel-mode", "--timid",
    }
    index = 0
    while index < len(run_args):
        value = run_args[index]
        lowered_value = value.casefold()
        if value == "--":
            index += 1
            break
        if lowered_value in {"-m", "--module"}:
            if index + 1 >= len(run_args):
                return NEUTRAL
            return _classify_simple(
                [run_args[index + 1], *run_args[index + 2 :]], depth + 1
            )
        option_name = lowered_value.split("=", 1)[0]
        if "=" in lowered_value and option_name in options_with_values:
            index += 1
            continue
        if lowered_value in options_with_values:
            if index + 1 >= len(run_args):
                return NEUTRAL
            index += 2
            continue
        if lowered_value in flag_options:
            index += 1
            continue
        if value.startswith("-"):
            return NEUTRAL
        break
    if index < len(run_args) and _script_name_is_evidence(run_args[index]):
        return EVIDENCE
    return NEUTRAL


def _classify_simple(values: list[str], depth: int = 0) -> str:
    """Classify a single command from executable/subcommand structure.

    This intentionally recognizes a bounded set of common engineering tools.
    Unknown commands are neutral; their arguments cannot become evidence merely
    by containing words such as `pytest` or `lint`.
    """
    values = _strip_prefixes(values)
    if not values:
        return NEUTRAL
    executable = _executable(values[0])
    args = values[1:]
    lowered = [value.casefold() for value in args]

    if _has_flag(lowered, {"-h", "--help", "--version"}):
        return NEUTRAL

    if depth < 2 and executable in {"bash", "sh", "zsh"}:
        if "-n" in lowered:
            return EVIDENCE
        for option in ("-c", "-lc"):
            if option in lowered:
                index = lowered.index(option)
                if index + 1 < len(args):
                    return _classify_command(args[index + 1], depth + 1)[0]
        if any(_script_name_is_mutation(value) for value in args):
            return MUTATION
        return EVIDENCE if any(_script_name_is_evidence(value) for value in args) else NEUTRAL

    if executable in {"powershell", "pwsh"}:
        if any(_script_name_is_mutation(value) for value in args):
            return MUTATION
        for option in ("-command", "-c"):
            if option in lowered:
                index = lowered.index(option)
                command_text = " ".join(args[index + 1 :])
                if re.search(
                    r"(?:^|[;|])\s*&?\s*(?:set-content|add-content|out-file|"
                    r"remove-item|copy-item|move-item|new-item)\b",
                    command_text,
                    re.IGNORECASE,
                ):
                    return MUTATION
        return EVIDENCE if any(_script_name_is_evidence(value) for value in args) else NEUTRAL

    if depth < 2 and executable in {"cmd"} and lowered[:1] in (["/c"], ["-c"]):
        return _classify_command(" ".join(args[1:]), depth + 1)[0]

    if depth < 2 and executable in {"npx", "bunx"} and args:
        return _classify_simple(args, depth + 1)
    if depth < 2 and executable == "pnpm" and lowered[:1] == ["dlx"]:
        return _classify_simple(args[1:], depth + 1)

    update_flags = {
        "-u", "--update", "--updatesnapshot", "--snapshot-update",
        "--update-snapshots",
    }
    if executable in {
        "pytest", "py.test", "unittest", "compileall", "py_compile",
        "doctest", "trial", "twisted.trial", "pytest-bdd", "pytest_bdd",
        "jest", "vitest", "mocha", "playwright",
    }:
        if _has_flag(lowered, update_flags):
            return MUTATION
        if executable == "playwright":
            return EVIDENCE if lowered[:1] == ["test"] else NEUTRAL
        return EVIDENCE

    if re.fullmatch(r"python\d*(?:\.\d+)?", executable):
        if lowered[:1] == ["-m"] and len(lowered) > 1:
            module = lowered[1]
            if module == "coverage":
                return _classify_simple([module, *args[2:]], depth + 1)
            if module in {
                "pytest", "unittest", "compileall", "py_compile", "doctest",
                "trial", "twisted.trial", "pytest-bdd", "pytest_bdd", "mypy",
                "ruff",
            }:
                return _classify_simple([module, *args[2:]], depth + 1)
        if args and _script_name_is_evidence(args[0]):
            return EVIDENCE
        if args and _script_name_is_mutation(args[0]):
            return MUTATION
        return NEUTRAL

    if executable == "coverage":
        return _classify_coverage_run(args, depth)

    if depth < 2 and executable in {"npm", "pnpm", "yarn", "bun"}:
        if lowered[:1] in (["exec"], ["x"]):
            return _classify_simple(args[1:], depth + 1)

    if executable in {"npm", "pnpm", "yarn", "bun"}:
        command_args = lowered
        if command_args[:1] == ["run"]:
            command_args = command_args[1:]
        action = command_args[0] if command_args else ""
        if _named(action, {"format", "fix", "generate", "codegen"}):
            return MUTATION
        if action in {"install", "update", "upgrade", "add", "remove", "uninstall", "ci", "dedupe"}:
            return MUTATION
        if _named(action, {"test", "lint", "check", "typecheck", "build", "verify", "validate", "audit"}):
            if _has_flag(command_args[1:], update_flags | {"--fix", "--write"}):
                return MUTATION
            return EVIDENCE
        return NEUTRAL

    if executable in {"eslint", "stylelint"}:
        return MUTATION if _has_flag(lowered, {"--fix", "--fix-dry-run"}) else EVIDENCE
    if executable == "ruff":
        if lowered[:1] == ["format"]:
            return EVIDENCE if "--check" in lowered else MUTATION
        if lowered[:1] == ["check"]:
            return MUTATION if "--fix" in lowered else EVIDENCE
        return NEUTRAL
    if executable == "prettier":
        if _has_flag(lowered, {"--write", "-w"}):
            return MUTATION
        return EVIDENCE if _has_flag(lowered, {"--check", "--list-different"}) else NEUTRAL
    if executable in {"black", "isort"}:
        return EVIDENCE if _has_flag(lowered, {"--check", "--check-only", "--diff"}) else MUTATION
    if executable in {"gofmt", "goimports"}:
        return MUTATION if "-w" in lowered else NEUTRAL
    if executable == "clang-format":
        if _has_flag(lowered, {"-i", "--in-place"}):
            return MUTATION
        if _has_flag(lowered, {"-n", "--dry-run"}) and "--werror" in lowered:
            return EVIDENCE
        return NEUTRAL
    if executable == "terraform" and lowered[:1] == ["fmt"]:
        return EVIDENCE if _has_flag(lowered, {"-check", "--check"}) else MUTATION
    if executable == "dotnet" and lowered[:1] == ["format"]:
        return EVIDENCE if "--verify-no-changes" in lowered else MUTATION

    if executable == "go":
        action = lowered[0] if lowered else ""
        if action in {"generate", "get", "install"} or lowered[:2] == ["mod", "tidy"]:
            return MUTATION
        return EVIDENCE if action in {"test", "vet", "build"} else NEUTRAL
    if executable == "cargo":
        action = lowered[0] if lowered else ""
        if action == "fmt":
            return EVIDENCE if "--check" in lowered else MUTATION
        if action == "llvm-cov":
            llvm_args = lowered[1:]
            if "clean" in llvm_args:
                return MUTATION
            if (
                any(value in {"report", "show-env"} for value in llvm_args)
                or "--ignore-run-fail" in llvm_args
            ):
                return NEUTRAL
            return EVIDENCE
        if action in {"add", "update", "install", "fix"}:
            return MUTATION
        return EVIDENCE if action in {"test", "check", "clippy", "build"} else NEUTRAL
    if executable == "dotnet":
        action = lowered[0] if lowered else ""
        if action in {"add", "remove", "restore", "tool"}:
            return MUTATION
        return EVIDENCE if action in {"test", "build"} else NEUTRAL

    if executable in {"pip", "pip3", "poetry", "uv", "gem"}:
        action = lowered[0] if lowered else ""
        if action in {"install", "uninstall", "add", "remove", "update", "upgrade", "sync", "lock"}:
            return MUTATION
        return NEUTRAL
    if executable == "bundle" and lowered[:1] in (["install"], ["update"]):
        return MUTATION

    if executable in {"mvn", "mvnw"}:
        return EVIDENCE if any(value in {"test", "verify", "package"} for value in lowered) else NEUTRAL
    if executable in {"gradle", "gradlew"}:
        return EVIDENCE if any(value in {"test", "check", "build"} for value in lowered) else NEUTRAL
    if executable in {"bazel", "buck", "buck2"}:
        return EVIDENCE if lowered[:1] in (["test"], ["build"]) else NEUTRAL
    if executable == "deno":
        return EVIDENCE if lowered[:1] in (["test"], ["lint"], ["check"]) else NEUTRAL
    if executable in {"make", "ninja"}:
        if any(value in {"clean", "install", "format", "generate", "codegen"} for value in lowered):
            return MUTATION
        return EVIDENCE
    if executable == "cmake":
        if "--install" in lowered:
            return MUTATION
        return EVIDENCE if "--build" in lowered else NEUTRAL
    if executable == "ctest":
        return EVIDENCE

    if executable in {
        "mypy", "pyright", "pylint", "flake8", "tox", "nox", "tsc",
        "shellcheck", "hadolint", "yamllint", "golangci-lint", "rustc",
        "rspec", "phpunit",
    }:
        return EVIDENCE
    if executable == "node" and "--check" in lowered:
        return EVIDENCE
    if executable == "ruby" and "-c" in lowered:
        return EVIDENCE
    if executable == "php" and "-l" in lowered:
        return EVIDENCE
    if executable == "bundle" and lowered[:2] == ["exec", "rspec"]:
        return EVIDENCE
    if executable == "composer":
        if lowered[:1] in (["install"], ["update"], ["require"], ["remove"]):
            return MUTATION
        return EVIDENCE if lowered[:1] in (["test"], ["check"]) else NEUTRAL
    if executable == "mix":
        return EVIDENCE if lowered[:1] == ["test"] else NEUTRAL
    if executable == "swift":
        return EVIDENCE if lowered[:1] in (["test"], ["build"]) else NEUTRAL
    if executable == "xcodebuild":
        return EVIDENCE if any(value in {"test", "build"} for value in lowered) else NEUTRAL
    if executable == "pre-commit":
        return EVIDENCE if lowered[:1] == ["run"] else NEUTRAL
    if executable == "agy":
        return EVIDENCE if lowered[:2] == ["plugin", "validate"] else NEUTRAL
    if executable == "git":
        if lowered[:2] == ["diff", "--check"]:
            return EVIDENCE
        if lowered[:1] in (["apply"], ["checkout"], ["restore"], ["reset"], ["clean"]):
            return MUTATION
        return NEUTRAL

    if executable in {
        "touch", "mkdir", "cp", "mv", "rm", "truncate", "tee", "patch", "chmod",
        "set-content", "add-content", "out-file", "remove-item", "copy-item",
        "move-item", "new-item",
    }:
        return MUTATION
    if executable == "sed" and any(value == "-i" or value.startswith("-i") for value in lowered):
        return MUTATION
    if executable == "perl" and any(value.startswith("-pi") for value in lowered):
        return MUTATION
    if executable in {"protoc", "openapi-generator", "graphql-codegen"}:
        return MUTATION
    if _script_name_is_mutation(values[0]):
        return MUTATION
    if _named(executable, {"generate", "codegen"}):
        return MUTATION
    if _script_name_is_evidence(values[0]):
        return EVIDENCE
    return NEUTRAL


def _is_print_waiver(values: list[str]) -> bool:
    values = _strip_prefixes(values)
    if not values:
        return False
    executable = _executable(values[0])
    if executable in {"echo", "printf", "write-output"}:
        return True
    return executable in {"powershell", "pwsh"} and any(
        value.casefold() == "write-output" for value in values[1:]
    )


def _has_output_redirection(values: list[str]) -> bool:
    return any(
        ">" in value and set(value) <= {"<", ">", "&"}
        for value in values
    )


def _classify_segment(values: list[str], depth: int = 0) -> tuple[str, bool]:
    """Classify a segment and preserve mutations hidden by command wrappers."""
    stripped = _strip_prefixes(values)
    if not stripped:
        return NEUTRAL, False

    executable = _executable(stripped[0])
    args = stripped[1:]
    lowered = [value.casefold() for value in args]
    if _has_flag(lowered, {"-h", "--help", "--version"}):
        return NEUTRAL, False

    if depth < 2 and executable in {"bash", "sh", "zsh"}:
        for option in ("-c", "-lc"):
            if option in lowered:
                index = lowered.index(option)
                if index + 1 < len(args):
                    kind, _, contains_mutation = _classify_command(
                        args[index + 1], depth + 1
                    )
                    return kind, contains_mutation

    if depth < 2 and executable in {"powershell", "pwsh"}:
        for option in ("-command", "-c"):
            if option in lowered:
                index = lowered.index(option)
                if index + 1 < len(args):
                    kind, _, contains_mutation = _classify_command(
                        " ".join(args[index + 1 :]), depth + 1
                    )
                    return kind, contains_mutation

    if depth < 2 and executable == "cmd" and lowered[:1] in (["/c"], ["-c"]):
        kind, _, contains_mutation = _classify_command(
            " ".join(args[1:]), depth + 1
        )
        return kind, contains_mutation

    kind = _classify_simple(stripped, depth)
    return kind, kind == MUTATION


def _classify_command(command: str, depth: int = 0) -> tuple[str, str, bool]:
    segments, unsafe = _tokens(command)
    waiver = _waiver_reason(command)
    if waiver and not unsafe and len(segments) == 1 and _is_print_waiver(segments[0]):
        if _has_output_redirection(segments[0]):
            return MUTATION, "", True
        return WAIVER, waiver, False

    kinds: list[str] = []
    contains_mutation = False
    for segment in segments:
        kind, nested_mutation = _classify_segment(segment, depth)
        has_output_redirection = _has_output_redirection(segment)
        contains_mutation = (
            contains_mutation
            or nested_mutation
            or kind == MUTATION
            or has_output_redirection
        )
        # Redirected output from a recognized check remains evidence; otherwise
        # redirection is a conservative workspace-mutation signal.
        if has_output_redirection and kind != EVIDENCE:
            kind = MUTATION
        kinds.append(kind)

    if unsafe:
        if contains_mutation:
            return MUTATION, "", True
        return NEUTRAL, "", False

    latest = NEUTRAL
    for kind in kinds:
        if kind in {MUTATION, EVIDENCE, WAIVER}:
            latest = kind
    return latest, "", contains_mutation


def _command_is_in_workspace(args: dict[str, Any], payload: dict[str, Any]) -> bool:
    if args.get("RunPersistent") is True:
        return False
    cwd = args.get("Cwd")
    if not isinstance(cwd, str) or not cwd.strip():
        return True
    roots = [
        _as_local_path(root)
        for root in payload.get("workspacePaths", [])
        if isinstance(root, str) and root.strip()
    ]
    if not roots:
        return True
    candidate = _as_local_path(cwd)
    return any(_is_within(candidate, root) for root in roots)


def _event(name: str, args: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    if name in WRITE_TOOLS and _is_workspace_write(args, payload):
        return {"kind": MUTATION}
    if name == "run_command" and _command_is_in_workspace(args, payload):
        kind, waiver, contains_mutation = _classify_command(_command(args))
        if kind in {MUTATION, EVIDENCE, WAIVER}:
            event: dict[str, Any] = {"kind": kind}
            if contains_mutation:
                event["containsMutation"] = True
            if waiver:
                event["waiverReason"] = waiver
            return event
    return {}


def _apply_event(state: dict[str, Any], event: dict[str, Any], step: int) -> bool:
    kind = event.get("kind")
    if kind == MUTATION:
        previous_write = state.get("lastWriteStep")
        if isinstance(previous_write, int) and step <= previous_write:
            return False
        state["lastWriteStep"] = step
        state["gateRetries"] = 0
        evidence_step = state.get("lastEvidenceStep")
        if not isinstance(evidence_step, int) or evidence_step <= step:
            state.pop("lastEvidenceStep", None)
            state.pop("evidence", None)
            state.pop("waiverReason", None)
        return True
    if kind in {EVIDENCE, WAIVER}:
        previous_evidence = state.get("lastEvidenceStep")
        if isinstance(previous_evidence, int) and step <= previous_evidence:
            return False
        state["lastEvidenceStep"] = step
        state["evidence"] = "no-runnable-check" if kind == WAIVER else "command"
        if kind == WAIVER:
            state["waiverReason"] = event.get("waiverReason", "")[:300]
        else:
            state.pop("waiverReason", None)
        return True
    return False


def _handle_post(payload: dict[str, Any]) -> None:
    # The primary target is Antigravity CLI, whose official PostToolUse payload
    # includes toolCall. Missing toolCall fails open; using PreToolUse as an
    # observer would require `decision: allow` and could bypass normal approval.
    step = _step(payload)
    if step < 0:
        _emit({})
        return

    name, args = _tool_call(payload)
    if not name:
        _emit({})
        return

    event = _event(name, args, payload)
    if payload.get("error"):
        if event.get("kind") == MUTATION or event.get("containsMutation") is True:
            # Earlier segments in an `&&` chain may have changed files before a
            # later check failed, even when the chain's final kind is evidence.
            event = {"kind": MUTATION}
        else:
            # A failed check or waiver is never evidence.
            _emit({})
            return
    if event:
        path = _state_path(payload)
        with _state_lock(path) as acquired:
            if not acquired:
                raise OSError(f"could not lock verification state: {path}")
            state = _load_state(path)
            if _apply_event(state, event, step):
                _save_state(path, state)

    _emit({})


def _normal_idle_stop(payload: dict[str, Any]) -> bool:
    if payload.get("fullyIdle") is not True or payload.get("error"):
        return False
    reason = str(payload.get("terminationReason", "")).upper()
    return not any(
        token in reason
        for token in ("ERROR", "MAX_STEP", "CANCEL", "INTERRUPT", "ABORT", "TIMEOUT")
    )


def _handle_stop(payload: dict[str, Any]) -> None:
    if not _normal_idle_stop(payload):
        _emit({"decision": "allow"})
        return

    path = _state_path(payload)
    with _state_lock(path) as acquired:
        if not acquired:
            raise OSError(f"could not lock verification state: {path}")
        state = _load_state(path)
        write_step = state.get("lastWriteStep")
        evidence_step = state.get("lastEvidenceStep")
        if not isinstance(write_step, int) or (
            isinstance(evidence_step, int) and evidence_step > write_step
        ):
            _emit({"decision": "allow"})
            return

        retries = state.get("gateRetries", 0)
        if not isinstance(retries, int):
            retries = 0
        if retries >= MAX_GATE_RETRIES:
            _emit(
                {
                    "decision": "allow",
                    "reason": "Verification is still missing; allowing stop after one reminder to avoid a loop.",
                }
            )
            return

        state["gateRetries"] = retries + 1
        _save_state(path, state)
    _emit(
        {
            "decision": "continue",
            "reason": (
                "Workspace files changed after the latest successful verification. "
                "Run the smallest relevant test, lint, type-check, or build command before finishing. "
                f"If no runnable check exists, run a command that prints `{NO_CHECK_MARKER} "
                "<specific reason>` and report that limitation in the final response. "
                "This gate retries once to avoid a loop."
            ),
        }
    )


def _fail_open(mode: str, payload: Optional[dict[str, Any]] = None) -> None:
    if mode == "stop":
        execution = (payload or {}).get("executionNum", 1)
        if execution == 0 and _normal_idle_stop(payload or {}):
            _emit(
                {
                    "decision": "continue",
                    "reason": (
                        "The verification gate could not read its state. Verify the latest workspace "
                        "changes, or explicitly report why no runnable check exists. The next stop will "
                        "be allowed to avoid a lockout."
                    ),
                }
            )
        else:
            _emit({"decision": "allow"})
    else:
        _emit({})


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    payload: Optional[dict[str, Any]] = None
    try:
        payload = _read_payload()
        _cleanup_fallback_states(payload)
        if mode == "post":
            _handle_post(payload)
        elif mode == "stop":
            _handle_stop(payload)
        else:
            _emit({})
    except Exception:
        _fail_open(mode, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
