#!/usr/bin/env python3
"""Bounded Stop hook for post-write evidence and local citation grounding.

The hook records step numbers, short evidence labels, and bounded workspace-
relative changed paths in the conversation artifact directory. It never
executes project checks itself. On compatible transcripts it also verifies
that explicit local file citations resolve inside the current workspace.
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
MAX_MODIFIED_PATHS = 32
MAX_TRANSCRIPT_TAIL_BYTES = 512 * 1024
MAX_TRANSCRIPT_LINES = 512
MAX_TRANSCRIPT_RECORD_BYTES = 256 * 1024
MAX_RESPONSE_BYTES = 128 * 1024
MAX_CITATIONS = 32
MAX_CITATION_LENGTH = 512
MAX_CITATION_SOURCE_BYTES = 8 * 1024 * 1024
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
_SCRIPT_BEHAVIOR_NAME = re.compile(
    r"(?:^|[-_.])(?:test|tests|spec|specs)(?:[-_.]|$)",
    re.IGNORECASE,
)
_STATIC_DOCUMENT_SUFFIXES = {".adoc", ".md", ".rst"}
_AMBIGUOUS_DOCUMENT_SUFFIXES = {".mdx", ".txt"}
_STATIC_DOCUMENT_NAMES = {
    ".editorconfig", ".gitattributes", ".gitignore", "authors", "changelog",
    "code_of_conduct", "contributing", "license", "notice", "readme",
}
_MARKDOWN_LINK = re.compile(
    r"(?<!!)\[[^\]\n]{1,256}\]\(\s*"
    r"(?:<([^>\n]{1,512})>|([^\s)\n]{1,512}))"
    r"(?:\s+(?:\"[^\"\n]{0,256}\"|'[^'\n]{0,256}'|\([^()\n]{0,256}\)))?\s*\)"
)
_RAW_FILE_URI = re.compile(r"file://[^\s<>)\]`]+", re.IGNORECASE)
_BAD_PERCENT_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")
_NON_FILE_URI_SCHEMES = {
    "codex", "data", "ftp", "ftps", "http", "https", "mailto", "sms",
    "ssh", "tel", "urn", "vscode",
}


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
    except (OSError, ValueError):
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


def _lexically_within(candidate: Path, root: Path) -> bool:
    try:
        Path(os.path.abspath(str(candidate))).relative_to(
            Path(os.path.abspath(str(root)))
        )
        return True
    except (OSError, ValueError):
        return False


def _safe_transcript_path(payload: dict[str, Any]) -> Optional[Path]:
    transcript_value = payload.get("transcriptPath")
    artifact_value = payload.get("artifactDirectoryPath")
    if not isinstance(transcript_value, str) or not transcript_value.strip():
        return None
    if not isinstance(artifact_value, str) or not artifact_value.strip():
        return None
    transcript = Path(transcript_value).expanduser()
    artifact = Path(artifact_value).expanduser()
    if not transcript.is_absolute() or not artifact.is_absolute():
        return None
    if transcript.name != "transcript.jsonl":
        return None
    if not _lexically_within(transcript, artifact):
        return None
    try:
        resolved_artifact = artifact.resolve(strict=True)
        resolved_transcript = transcript.resolve(strict=True)
    except OSError:
        return None
    if not _is_within(resolved_transcript, resolved_artifact):
        return None
    return transcript


def _read_transcript_tail(payload: dict[str, Any]) -> Optional[list[str]]:
    path = _safe_transcript_path(payload)
    if path is None:
        return None
    try:
        with _open_regular_file(path, os.O_RDONLY) as handle:
            size = os.fstat(handle.fileno()).st_size
            start = max(0, size - MAX_TRANSCRIPT_TAIL_BYTES)
            handle.seek(start)
            data = handle.read(size - start)
    except OSError:
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    lines = [
        line[:-1] if line.endswith("\r") else line
        for line in text.split("\n")
    ]
    if start > 0 and lines:
        lines = lines[1:]
    return lines[-MAX_TRANSCRIPT_LINES:]


def _content_was_truncated(record: dict[str, Any]) -> bool:
    truncated = record.get("truncated_fields")
    if isinstance(truncated, str):
        return truncated.casefold() == "content"
    if isinstance(truncated, list):
        return any(
            isinstance(value, str) and value.casefold() == "content"
            for value in truncated
        )
    return False


def _latest_model_response(
    payload: dict[str, Any]
) -> Optional[tuple[str, int, int]]:
    lines = _read_transcript_tail(payload)
    if lines is None:
        return None
    records: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        if len(line.encode("utf-8")) > MAX_TRANSCRIPT_RECORD_BYTES:
            return None
        try:
            record = json.loads(line)
        except (TypeError, ValueError):
            return None
        if not isinstance(record, dict):
            return None
        records.append(record)

    user_steps = [
        record.get("step_index")
        for record in records
        if str(record.get("source", "")).upper() in {"USER", "USER_EXPLICIT"}
        and str(record.get("type", "")).upper() in {"REQUEST", "USER_INPUT"}
        and isinstance(record.get("step_index"), int)
        and not isinstance(record.get("step_index"), bool)
    ]
    if not user_steps:
        return None
    user_step = max(user_steps)

    for record in reversed(records):
        if str(record.get("source", "")).upper() != "MODEL":
            continue
        step = record.get("step_index")
        if not isinstance(step, int) or isinstance(step, bool) or step <= user_step:
            return None
        if str(record.get("type", "")).upper() != "PLANNER_RESPONSE":
            return None
        if str(record.get("status", "")).upper() != "DONE":
            return None
        if _content_was_truncated(record) or record.get("tool_calls"):
            return None
        content = record.get("content")
        if not isinstance(content, str):
            return None
        if len(content.encode("utf-8")) > MAX_RESPONSE_BYTES:
            return None
        return content, user_step, step
    return None


def _without_markdown_code_or_images(text: str) -> str:
    visible: list[str] = []
    fence: Optional[str] = None
    for line in text.splitlines():
        stripped = line.lstrip()
        marker = stripped[:3]
        if marker in {"```", "~~~"}:
            if fence is None:
                fence = marker
            elif fence == marker:
                fence = None
            continue
        if fence is None:
            visible.append(line)
    result = "\n".join(visible)
    result = re.sub(r"`+[^`\n]*`+", "", result)
    return re.sub(r"!\[[^\]\n]*\]\([^\n)]*\)", "", result)


def _explicit_citation_targets(text: str) -> Optional[list[str]]:
    visible = _without_markdown_code_or_images(text)
    targets: list[str] = []
    for match in _MARKDOWN_LINK.finditer(visible):
        targets.append(match.group(1) or match.group(2))
    targets.extend(
        match.group(0).rstrip(".,;") for match in _RAW_FILE_URI.finditer(visible)
    )
    unique = list(dict.fromkeys(targets))
    return unique if len(unique) <= MAX_CITATIONS else None


def _citation_line_range(
    path_value: str, fragment: str
) -> tuple[str, Optional[int], Optional[int]]:
    if fragment:
        match = re.fullmatch(r"L(\d+)(?:-L?(\d+))?", fragment, re.IGNORECASE)
        if match:
            start = int(match.group(1))
            end = int(match.group(2) or match.group(1))
            return path_value, start, end
        return path_value, None, None

    match = re.fullmatch(r"^(.*):(\d+)-(\d+)$", path_value)
    if match:
        return match.group(1), int(match.group(2)), int(match.group(3))
    match = re.fullmatch(r"^(.*):(\d+):(\d+)$", path_value)
    if match:
        if int(match.group(3)) < 1:
            raise ValueError("invalid citation")
        line = int(match.group(2))
        return match.group(1), line, line
    match = re.fullmatch(r"^(.*):(\d+)$", path_value)
    if match:
        line = int(match.group(2))
        return match.group(1), line, line
    return path_value, None, None


def _parse_local_citation(
    raw_target: str,
) -> Optional[tuple[str, Optional[int], Optional[int]]]:
    target = raw_target.strip()
    if len(target) > MAX_CITATION_LENGTH or not target:
        raise ValueError("invalid citation")
    if any(ord(character) < 32 for character in target):
        raise ValueError("invalid citation")
    if _BAD_PERCENT_ESCAPE.search(target):
        raise ValueError("invalid citation")

    lowered = target.casefold()
    if target.startswith("#"):
        return None
    scheme = urlparse(target).scheme.casefold()
    if scheme in _NON_FILE_URI_SCHEMES:
        return None
    fragment = ""
    if lowered.startswith("file://"):
        parsed = urlparse(target)
        if parsed.scheme.casefold() != "file" or parsed.netloc or parsed.query:
            raise ValueError("invalid citation")
        path_value = unquote(parsed.path)
        fragment = unquote(parsed.fragment)
        if os.name == "nt" and re.match(r"^/[A-Za-z]:/", path_value):
            path_value = path_value[1:]
    else:
        if "://" in target:
            return None
        if "?" in target:
            raise ValueError("invalid citation")
        path_value, separator, fragment = target.partition("#")
        if separator and "#" in fragment:
            raise ValueError("invalid citation")
        path_value = unquote(path_value)
        fragment = unquote(fragment)
    if any(ord(character) < 32 for character in path_value + fragment):
        raise ValueError("invalid citation")
    if not path_value:
        raise ValueError("invalid citation")
    return _citation_line_range(path_value, fragment)


def _open_workspace_source(path: Path) -> Optional[Any]:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(str(path), flags)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            os.close(descriptor)
            return None
        return os.fdopen(descriptor, "rb", buffering=0)
    except (OSError, ValueError):
        return None


def _citation_file_result(
    path_value: str,
    start_line: Optional[int],
    end_line: Optional[int],
    payload: dict[str, Any],
) -> Optional[bool]:
    if start_line is not None and (
        start_line < 1 or end_line is None or end_line < start_line
    ):
        return False
    root_values = payload.get("workspacePaths")
    if not isinstance(root_values, list) or not root_values:
        return None
    roots: list[tuple[Path, Path]] = []
    for root_value in root_values:
        if not isinstance(root_value, str) or not root_value.strip():
            return None
        declared_root = _as_local_path(root_value)
        if not declared_root.is_absolute():
            return None
        try:
            resolved_root = declared_root.resolve(strict=True)
        except (OSError, ValueError):
            return None
        if not resolved_root.is_dir() or resolved_root == Path(resolved_root.anchor):
            return None
        roots.append((declared_root, resolved_root))

    citation_path = _as_local_path(path_value)
    lexical_candidates: list[tuple[Path, Path]] = []
    if citation_path.is_absolute():
        for declared_root, resolved_root in roots:
            if _lexically_within(citation_path, declared_root) or _lexically_within(
                citation_path, resolved_root
            ):
                lexical_candidates.append((citation_path, resolved_root))
    else:
        for declared_root, resolved_root in roots:
            candidate = declared_root / citation_path
            if _lexically_within(candidate, declared_root):
                lexical_candidates.append((candidate, resolved_root))
    if not lexical_candidates:
        return False

    resolved_matches: dict[str, Path] = {}
    for candidate, resolved_root in lexical_candidates:
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, ValueError):
            continue
        if not _is_within(resolved, resolved_root):
            continue
        handle = _open_workspace_source(resolved)
        if handle is None:
            continue
        handle.close()
        resolved_matches[str(resolved)] = resolved
    if len(resolved_matches) != 1:
        return False
    resolved = next(iter(resolved_matches.values()))
    if start_line is None:
        return True

    handle = _open_workspace_source(resolved)
    if handle is None:
        return False
    with handle:
        size = os.fstat(handle.fileno()).st_size
        if size > MAX_CITATION_SOURCE_BYTES:
            return None
        data = handle.read(MAX_CITATION_SOURCE_BYTES + 1)
    if len(data) > MAX_CITATION_SOURCE_BYTES:
        return None
    line_count = data.count(b"\n")
    if data and not data.endswith(b"\n"):
        line_count += 1
    return end_line is not None and end_line <= line_count


def _citation_status(payload: dict[str, Any]) -> tuple[str, Optional[int]]:
    latest = _latest_model_response(payload)
    if latest is None:
        return "unavailable", None
    content, user_step, _ = latest
    targets = _explicit_citation_targets(content)
    if targets is None:
        return "invalid", user_step
    unsupported = False
    for raw_target in targets:
        try:
            parsed = _parse_local_citation(raw_target)
        except ValueError:
            return "invalid", user_step
        if parsed is None:
            continue
        result = _citation_file_result(*parsed, payload)
        if result is False:
            return "invalid", user_step
        if result is None:
            unsupported = True
    return ("unavailable" if unsupported else "valid"), user_step


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


def _workspace_relative_target(
    args: dict[str, Any], payload: dict[str, Any]
) -> Optional[str]:
    target = args.get("TargetFile")
    if not isinstance(target, str) or not target.strip():
        return None
    roots = [
        _as_local_path(root)
        for root in payload.get("workspacePaths", [])
        if isinstance(root, str) and root.strip()
    ]
    candidate = _as_local_path(target)
    if not roots:
        return candidate.name[:240] if candidate.is_absolute() else candidate.as_posix()[:240]
    if not candidate.is_absolute():
        candidate = roots[0] / candidate
    for root in roots:
        try:
            relative = candidate.resolve(strict=False).relative_to(root.resolve(strict=False))
        except (OSError, ValueError):
            continue
        value = relative.as_posix()
        return value[:240] if value and value != "." else None
    return None


def _requires_behavioral_verification(path: Optional[str]) -> bool:
    if path is None:
        return True
    candidate = Path(path)
    suffix = candidate.suffix.casefold()
    name = candidate.name.casefold()
    stem = candidate.stem.casefold()
    is_document = (
        suffix in _STATIC_DOCUMENT_SUFFIXES
        or name in _STATIC_DOCUMENT_NAMES
        or (suffix in _AMBIGUOUS_DOCUMENT_SUFFIXES and stem in _STATIC_DOCUMENT_NAMES)
    )
    return not is_document


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


def _script_name_is_behavioral(value: str) -> bool:
    name = value.replace("\\", "/").rsplit("/", 1)[-1]
    stem, dot, extension = name.rpartition(".")
    if not dot or extension.casefold() not in {"sh", "py", "ps1", "cmd", "bat"}:
        return False
    return bool(_SCRIPT_BEHAVIOR_NAME.search(stem))


def _named(value: str, names: set[str]) -> bool:
    value = value.casefold()
    return any(value == name or value.startswith(f"{name}:") for name in names)


def _has_flag(values: list[str], flags: set[str]) -> bool:
    return any(value.casefold() in flags for value in values)


def _gradle_task_key(value: str) -> Optional[str]:
    if not value or value.startswith("-") or "=" in value:
        return None
    return value.casefold()


def _gradle_task_is_verification(value: str) -> bool:
    key = _gradle_task_key(value)
    if key is None:
        return False
    task = key.rsplit(":", 1)[-1]
    return task in {"build", "check", "test"} or task.endswith("test")


def _gradle_task_is_behavioral(value: str) -> bool:
    key = _gradle_task_key(value)
    if key is None:
        return False
    task = key.rsplit(":", 1)[-1]
    return task in {"check", "test"} or task.endswith("test")


def _gradle_tasks(values: list[str]) -> tuple[set[str], set[str]]:
    requested: set[str] = set()
    excluded: set[str] = set()
    options_with_values = {
        "-b", "--build-file", "-c", "--settings-file", "-g",
        "--gradle-user-home", "--include-build", "--max-workers", "-p",
        "--project-cache-dir", "--project-dir",
    }
    index = 0
    while index < len(values):
        value = values[index]
        lowered = value.casefold()
        if lowered in {"-x", "--exclude-task"}:
            if index + 1 < len(values):
                key = _gradle_task_key(values[index + 1])
                if key is not None:
                    excluded.add(key)
            index += 2
            continue
        if lowered in options_with_values:
            index += 2
            continue
        if lowered.startswith("--exclude-task="):
            key = _gradle_task_key(value.split("=", 1)[1])
            if key is not None:
                excluded.add(key)
            index += 1
            continue
        key = _gradle_task_key(value)
        if key is not None:
            requested.add(key)
        index += 1
    return requested, excluded


def _gradle_task_is_excluded(requested: str, excluded: set[str]) -> bool:
    if requested in excluded:
        return True
    requested_leaf = requested.rsplit(":", 1)[-1]
    return any(
        ":" not in excluded_task and excluded_task == requested_leaf
        for excluded_task in excluded
    )


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
        requested, _ = _gradle_tasks(args)
        return EVIDENCE if any(
            _gradle_task_is_verification(value) for value in requested
        ) else NEUTRAL
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
    if executable == "node" and any(value in {"--check", "--test"} for value in lowered):
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
        return EVIDENCE if any(
            value in {"build", "build-for-testing", "test", "test-without-building"}
            for value in lowered
        ) else NEUTRAL
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


def _simple_has_behavioral_evidence(values: list[str], depth: int = 0) -> bool:
    values = _strip_prefixes(values)
    if not values or _classify_simple(values, depth) != EVIDENCE:
        return False
    executable = _executable(values[0])
    args = values[1:]
    lowered = [value.casefold() for value in args]

    if depth < 2 and executable in {"bash", "sh", "zsh"}:
        for option in ("-c", "-lc"):
            if option in lowered:
                index = lowered.index(option)
                return index + 1 < len(args) and _command_has_behavioral_evidence(
                    args[index + 1], depth + 1
                )
        return any(_script_name_is_behavioral(value) for value in args)
    if depth < 2 and executable in {"powershell", "pwsh"}:
        for option in ("-command", "-c"):
            if option in lowered:
                index = lowered.index(option)
                return index + 1 < len(args) and _command_has_behavioral_evidence(
                    " ".join(args[index + 1 :]), depth + 1
                )
        return any(_script_name_is_behavioral(value) for value in args)
    if depth < 2 and executable == "cmd" and lowered[:1] in (["/c"], ["-c"]):
        return _command_has_behavioral_evidence(" ".join(args[1:]), depth + 1)
    if depth < 2 and executable in {"npx", "bunx"} and args:
        return _simple_has_behavioral_evidence(args, depth + 1)
    if depth < 2 and executable == "pnpm" and lowered[:1] == ["dlx"]:
        return _simple_has_behavioral_evidence(args[1:], depth + 1)

    if executable in {
        "pytest", "py.test", "unittest", "doctest", "trial", "twisted.trial",
        "pytest-bdd", "pytest_bdd", "jest", "vitest", "mocha",
    }:
        if executable in {"pytest", "py.test", "pytest-bdd", "pytest_bdd"} and _has_flag(
            lowered, {"--collect-only", "--co"}
        ):
            return False
        if executable == "jest" and _has_flag(lowered, {"--listtests", "--list-tests"}):
            return False
        if executable == "vitest" and (
            lowered[:1] == ["list"] or _has_flag(lowered, {"--list"})
        ):
            return False
        return True
    if executable == "playwright":
        return lowered[:1] == ["test"] and "--list" not in lowered
    if re.fullmatch(r"python\d*(?:\.\d+)?", executable):
        if lowered[:1] == ["-m"] and len(args) > 1:
            return _simple_has_behavioral_evidence([args[1], *args[2:]], depth + 1)
        return bool(args and _script_name_is_behavioral(args[0]))
    if executable == "coverage":
        if lowered[:1] != ["run"]:
            return False
        if "-m" in lowered or "--module" in lowered:
            option = "-m" if "-m" in lowered else "--module"
            index = lowered.index(option)
            return index + 1 < len(args) and _simple_has_behavioral_evidence(
                [args[index + 1], *args[index + 2 :]], depth + 1
            )
        return any(_script_name_is_behavioral(value) for value in args)

    if depth < 2 and executable in {"npm", "pnpm", "yarn", "bun"}:
        if lowered[:1] in (["exec"], ["x"]):
            return _simple_has_behavioral_evidence(args[1:], depth + 1)
        command_args = lowered[1:] if lowered[:1] == ["run"] else lowered
        action = command_args[0] if command_args else ""
        if _has_flag(
            command_args[1:],
            {"--collect-only", "--list", "--list-tests", "--listtests", "--no-run"},
        ):
            return False
        return _named(action, {"test"})
    if executable == "go":
        return lowered[:1] == ["test"]
    if executable == "cargo":
        return (
            lowered[:1] in (["test"], ["llvm-cov"])
            and "--no-run" not in lowered
            and "--list" not in lowered
        )
    if executable in {"mvn", "mvnw"}:
        skipped = any(
            value == "-dskiptests"
            or value in {"-dskiptests=true", "-dmaven.test.skip=true"}
            for value in lowered
        )
        return not skipped and any(
            value in {"test", "verify", "package"} for value in lowered
        )
    if executable in {"gradle", "gradlew"}:
        if _has_flag(lowered, {"-m", "--dry-run"}):
            return False
        requested, excluded = _gradle_tasks(args)
        return any(
            _gradle_task_is_behavioral(value)
            and not _gradle_task_is_excluded(value, excluded)
            for value in requested
        )
    if executable in {"bazel", "buck", "buck2"}:
        return lowered[:1] == ["test"]
    if executable == "deno":
        return lowered[:1] == ["test"]
    if executable in {"make", "ninja"}:
        return any(_named(value, {"test"}) for value in lowered)
    if executable == "ctest":
        return (
            "-n" not in lowered
            and "--show-only" not in lowered
            and not any(value.startswith("--show-only=") for value in lowered)
        )
    if executable == "tox":
        return not _has_flag(lowered, {"-l", "--listenvs", "--list-envs", "--showconfig"})
    if executable == "nox":
        return not _has_flag(lowered, {"-l", "--list", "--list-sessions", "--list_sessions"})
    if executable in {"rspec", "phpunit"}:
        return True
    if executable == "bundle":
        return lowered[:2] == ["exec", "rspec"]
    if executable == "mix":
        return lowered[:1] == ["test"]
    if executable == "swift":
        return lowered[:1] == ["test"]
    if executable == "xcodebuild":
        return any(value in {"test", "test-without-building"} for value in lowered)
    if executable == "composer":
        return lowered[:1] == ["test"]
    if executable == "dotnet":
        return lowered[:1] == ["test"] and not _has_flag(
            lowered, {"-t", "--list-tests"}
        )
    if executable == "node":
        return "--test" in lowered
    return _script_name_is_behavioral(values[0])


def _command_has_behavioral_evidence(command: str, depth: int = 0) -> bool:
    segments, unsafe = _tokens(command)
    if unsafe:
        return False
    behavioral_after_latest_mutation = False
    for segment in segments:
        kind, nested_mutation = _classify_segment(segment, depth)
        has_output_redirection = _has_output_redirection(segment)
        if nested_mutation or kind == MUTATION or has_output_redirection:
            behavioral_after_latest_mutation = False
        # Nested shell commands perform their own ordered scan. For an output
        # redirect, the file is opened before the command runs, so a behavioral
        # check in the same segment still verifies the resulting workspace.
        if kind == EVIDENCE and _simple_has_behavioral_evidence(segment, depth):
            behavioral_after_latest_mutation = True
    return behavioral_after_latest_mutation


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
        path = _workspace_relative_target(args, payload)
        return {
            "kind": MUTATION,
            "modifiedPath": path,
            "requiresBehavioral": _requires_behavioral_verification(path),
        }
    if name == "run_command" and _command_is_in_workspace(args, payload):
        command = _command(args)
        kind, waiver, contains_mutation = _classify_command(command)
        behavioral = kind == EVIDENCE and _command_has_behavioral_evidence(command)
        # An ordered chain such as `formatter && static-check` still changes
        # runtime-facing files without exercising behavior. Preserve it as a
        # mutation so the static tail cannot hide the need for a real test.
        if kind == EVIDENCE and contains_mutation and not behavioral:
            kind = MUTATION
        if kind in {MUTATION, EVIDENCE, WAIVER}:
            event: dict[str, Any] = {"kind": kind}
            if contains_mutation:
                event["containsMutation"] = True
            if kind == MUTATION:
                event["requiresBehavioral"] = True
            if behavioral:
                event["behavioral"] = True
            if waiver:
                event["waiverReason"] = waiver
            return event
    return {}


def _apply_event(state: dict[str, Any], event: dict[str, Any], step: int) -> bool:
    kind = event.get("kind")
    if kind == MUTATION:
        previous_write = state.get("lastWriteStep")
        changed = False
        if not isinstance(previous_write, int) or step > previous_write:
            previous_evidence = state.get("lastEvidenceStep")
            if (
                isinstance(previous_write, int)
                and isinstance(previous_evidence, int)
                and previous_evidence > previous_write
                and step > previous_evidence
            ):
                state.pop("modifiedPaths", None)
            state["lastWriteStep"] = step
            state["gateRetries"] = 0
            changed = True
        if event.get("requiresBehavioral") is True:
            previous_behavioral_write = state.get("lastBehavioralWriteStep")
            if not isinstance(previous_behavioral_write, int) or step > previous_behavioral_write:
                state["lastBehavioralWriteStep"] = step
                changed = True
        modified_path = event.get("modifiedPath")
        if isinstance(modified_path, str) and modified_path:
            paths = state.get("modifiedPaths")
            if not isinstance(paths, list):
                paths = []
            bounded = [
                value[:240]
                for value in paths
                if isinstance(value, str) and value
            ][:MAX_MODIFIED_PATHS]
            if modified_path not in bounded and len(bounded) < MAX_MODIFIED_PATHS:
                bounded.append(modified_path[:240])
                state["modifiedPaths"] = bounded
                changed = True
        evidence_step = state.get("lastEvidenceStep")
        if not isinstance(evidence_step, int) or evidence_step <= step:
            state.pop("lastEvidenceStep", None)
            state.pop("evidence", None)
            state.pop("waiverReason", None)
        return changed
    if kind in {EVIDENCE, WAIVER}:
        changed = False
        if kind == EVIDENCE and event.get("behavioral") is True:
            previous_behavioral = state.get("lastBehavioralEvidenceStep")
            if not isinstance(previous_behavioral, int) or step > previous_behavioral:
                state["lastBehavioralEvidenceStep"] = step
                changed = True
        if kind == WAIVER:
            previous_waiver = state.get("lastWaiverStep")
            if not isinstance(previous_waiver, int) or step > previous_waiver:
                state["lastWaiverStep"] = step
                changed = True
        previous_evidence = state.get("lastEvidenceStep")
        if isinstance(previous_evidence, int) and step <= previous_evidence:
            return changed
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
            event = {"kind": MUTATION, "requiresBehavioral": True}
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

    citation_status, citation_turn_step = _citation_status(payload)
    path = _state_path(payload)
    with _state_lock(path) as acquired:
        if not acquired:
            raise OSError(f"could not lock verification state: {path}")
        state = _load_state(path)
        state_changed = False
        continue_reasons: list[str] = []
        warnings: list[str] = []

        if isinstance(citation_turn_step, int):
            previous_turn = state.get("citationTurnStep")
            if not isinstance(previous_turn, int) or citation_turn_step != previous_turn:
                state["citationTurnStep"] = citation_turn_step
                state["citationGateRetries"] = 0
                state_changed = True
        if citation_status == "valid":
            if state.pop("citationGateRetries", None) is not None:
                state_changed = True
        elif citation_status == "invalid":
            retries = state.get("citationGateRetries", 0)
            if not isinstance(retries, int):
                retries = 0
            if retries < MAX_GATE_RETRIES:
                state["citationGateRetries"] = retries + 1
                state_changed = True
                continue_reasons.append(
                    "One or more explicit local file citations are not grounded in a "
                    "current regular workspace file and valid line range. Re-check every local "
                    "citation and correct or remove unsupported references. No outside-workspace "
                    "file content was opened or read. The citation gate retries once to avoid a loop."
                )
            else:
                warnings.append(
                    "Citation grounding is still invalid; allowing stop after one reminder to "
                    "avoid a loop."
                )

        write_step = state.get("lastWriteStep")
        evidence_step = state.get("lastEvidenceStep")
        behavioral_write_step = state.get("lastBehavioralWriteStep")
        behavioral_evidence_step = state.get("lastBehavioralEvidenceStep")
        waiver_step = state.get("lastWaiverStep")
        has_current_evidence = (
            isinstance(evidence_step, int) and evidence_step > write_step
        ) if isinstance(write_step, int) else False
        has_behavioral_evidence = not isinstance(behavioral_write_step, int) or any(
            isinstance(candidate, int) and candidate > behavioral_write_step
            for candidate in (behavioral_evidence_step, waiver_step)
        )
        verification_missing = isinstance(write_step, int) and not (
            has_current_evidence and has_behavioral_evidence
        )
        if verification_missing:
            retries = state.get("gateRetries", 0)
            if not isinstance(retries, int):
                retries = 0
            if retries < MAX_GATE_RETRIES:
                state["gateRetries"] = retries + 1
                state_changed = True
                if isinstance(behavioral_write_step, int) and not has_behavioral_evidence:
                    continue_reasons.append(
                        "Workspace files changed in logic or unknown scope without later behavioral "
                        "verification. Run the smallest relevant unit, integration, or regression "
                        "test; a format, lint, type-check, or build-only command is not sufficient "
                        f"for this scope. If no behavioral check can run, print `{NO_CHECK_MARKER} "
                        "<specific reason>` and report the limitation in the final response. This "
                        "gate retries once to avoid a loop."
                    )
                else:
                    continue_reasons.append(
                        "Workspace files changed after the latest successful verification. Run the "
                        "smallest relevant test, lint, type-check, or build command before finishing. "
                        f"If no runnable check exists, run a command that prints `{NO_CHECK_MARKER} "
                        "<specific reason>` and report that limitation in the final response. This "
                        "gate retries once to avoid a loop."
                    )
            else:
                warnings.append(
                    "Verification is still missing; allowing stop after one reminder to avoid a loop."
                )
        if state_changed:
            _save_state(path, state)

    if continue_reasons:
        _emit(
            {
                "decision": "continue",
                "reason": " ".join([*continue_reasons, *warnings]),
            }
        )
    elif warnings:
        _emit({"decision": "allow", "reason": " ".join(warnings)})
    else:
        _emit({"decision": "allow"})


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
