#!/usr/bin/env python3
"""Bounded security, project-context, and opt-in formatting hooks.

The security hook deliberately reports categories, never matched values. The
context hook reads only small, known manifest files. The formatter never
installs tools and cannot block an otherwise successful write.
"""

from __future__ import annotations

import base64
from contextlib import contextmanager
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple


WRITE_TOOLS = {
    "write_to_file",
    "replace_file_content",
    "multi_replace_file_content",
}
MAX_SCAN_CHARS = 256 * 1024
MAX_MANIFEST_BYTES = 256 * 1024
MAX_GIT_OUTPUT_BYTES = 512 * 1024
MAX_CONTEXT_BYTES = 1024
COMMAND_TIMEOUT_SECONDS = 3.0
FORMAT_TIMEOUT_SECONDS = 5.0
LOCK_WAIT_SECONDS = 0.1
FORMAT_LOCK_PREFIX = "codex-harness-format-"
FORMAT_LOCK_DIRECTORY_PREFIX = "codex-harness-format-locks-"
FORMAT_LOCK_TTL_SECONDS = 48 * 60 * 60
_FORMAT_LOCK_NAME = re.compile(
    r"^%s[0-9a-f]{24}\.lock$" % re.escape(FORMAT_LOCK_PREFIX)
)

_PRIVATE_KEY_HEADER = re.compile(
    r"-----BEGIN (?:(?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY|"
    r"PGP PRIVATE KEY BLOCK)-----",
    re.IGNORECASE,
)
_PRIVATE_KEY_BLOCK = re.compile(
    r"-----BEGIN ((?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY|"
    r"PGP PRIVATE KEY BLOCK)-----\s*(.*?)\s*-----END \1-----",
    re.IGNORECASE | re.DOTALL,
)
_KNOWN_TOKEN = re.compile(
    r"(?:"
    r"gh[pousr]_[A-Za-z0-9]{36,255}|"
    r"github_pat_[A-Za-z0-9_]{40,255}|"
    r"glpat-[A-Za-z0-9_-]{20,255}|"
    r"xox[baprs]-[A-Za-z0-9-]{20,255}|"
    r"sk_live_[A-Za-z0-9]{20,255}|"
    r"AKIA[0-9A-Z]{16}"
    r")"
)
_AWS_SECRET = re.compile(
    r"(?:AWS_SECRET_ACCESS_KEY|aws_secret_access_key)\s*[:=]\s*[\"']?"
    r"[A-Za-z0-9/+=]{40}(?![A-Za-z0-9/+=])",
    re.IGNORECASE,
)
_JWT = re.compile(
    r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\."
    r"[A-Za-z0-9_-]{8,}(?![A-Za-z0-9_-])"
)
_AMBIGUOUS_ASSIGNMENT = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|"
    r"password|passwd|secret)\s*[:=]\s*[\"']([^\"'\s]{8,})[\"']"
)
_SAFE_VALUE = re.compile(
    r"(?i)^(?:\$\{?\w+\}?|process\.env\.\w+|os\.(?:environ|getenv).+|"
    r"replace[-_ ]?me|change[-_ ]?me|example|sample|dummy|test|redacted|x+|\*+)$"
)
_SENSITIVE_ENV = re.compile(
    r"(?i)(?<![A-Za-z0-9_.-])(?:[^\s'\";|&<>]*[/\\])?"
    r"\.env(?:rc|[._-][A-Za-z0-9_.-]*)?(?![A-Za-z0-9_.-])"
)
_SAFE_ENV_NAMES = {".env.example", ".env.sample", ".env.template"}
_ENV_EGRESS_COMMAND = re.compile(
    r"(?i)(?:^|[;&|()]\s*|\s)(?:cat|head|tail|less|more|type|Get-Content|"
    r"Select-String|sed|awk|grep|rg|curl|wget|scp|rsync|nc|ncat|http|https|"
    r"Invoke-WebRequest|Invoke-RestMethod)\b"
)
_GIT_ENV_OUTPUT = re.compile(
    r"(?i)(?:^|[;&|()]\s*|\s)git\b[^;&|\r\n]*?\b(?:show|diff)\b"
)
_SCRIPT_ENV_OUTPUT = re.compile(
    r"(?i)(?:\bprint\s*\(|\bconsole\.log\s*\(|\bsys\.stdout\b)"
)
_ENV_EGRESS_EXECUTABLES = (
    "cat", "head", "tail", "less", "more", "type", "get-content",
    "select-string", "sed", "awk", "grep", "rg", "curl", "wget",
    "scp", "rsync", "nc", "ncat", "http", "https", "invoke-webrequest",
    "invoke-restmethod",
)
_GIT_COMMIT_ALL = re.compile(
    r"(?i)\bgit\b[^;&|\r\n]*\bcommit\b[^;&|\r\n]*"
    r"(?:(?<!\S)-[A-Za-z]*a[A-Za-z]*(?=\s|$)|--all\b)"
)
_GIT_COMMIT_TREE_MODES = {
    "--all", "--include", "--only", "--interactive", "--patch",
    "--pathspec-from-file", "--pathspec-file-nul",
}

_PRETTIER_EXTENSIONS = {
    ".css", ".graphql", ".html", ".js", ".json", ".jsx", ".less",
    ".md", ".mdx", ".mjs", ".cjs", ".scss", ".ts", ".tsx", ".vue",
    ".yaml", ".yml",
}
_PRETTIER_CONFIGS = {
    ".prettierrc", ".prettierrc.json", ".prettierrc.yml",
    ".prettierrc.yaml", ".prettierrc.json5", ".prettierrc.toml",
    ".prettierrc.js", ".prettierrc.cjs", ".prettierrc.mjs",
    ".prettierrc.ts", ".prettierrc.cts", ".prettierrc.mts",
    "prettier.config.js", "prettier.config.cjs", "prettier.config.mjs",
    "prettier.config.ts", "prettier.config.cts", "prettier.config.mts",
}
_CHECK_NAMES = {"build", "check", "lint", "test", "typecheck", "validate", "verify"}


class ScanIncomplete(Exception):
    """Raised when a security decision cannot be made within fixed bounds."""


def _emit(value: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(value, separators=(",", ":")) + "\n")


def _read_payload() -> Dict[str, Any]:
    payload = json.load(sys.stdin)
    if not isinstance(payload, dict):
        raise ValueError("hook payload must be an object")
    return payload


def _tool_call(payload: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    call = payload.get("toolCall")
    if not isinstance(call, dict):
        raise ScanIncomplete("missing tool call")
    name = call.get("name")
    args = call.get("args")
    if not isinstance(name, str) or not isinstance(args, dict):
        raise ScanIncomplete("invalid tool call")
    return name, args


def _bounded_join(values: Sequence[str]) -> str:
    total = 0
    result: List[str] = []
    for value in values:
        total += len(value)
        if total > MAX_SCAN_CHARS:
            raise ScanIncomplete("content exceeds scan bound")
        result.append(value)
    return "\n".join(result)


def _write_content(name: str, args: Dict[str, Any]) -> str:
    if name == "write_to_file":
        if "CodeContent" not in args:
            raise ScanIncomplete("missing write content")
        value = args.get("CodeContent")
        if not isinstance(value, str):
            raise ScanIncomplete("invalid write content")
        return _bounded_join([value])
    if name == "replace_file_content":
        if "ReplacementContent" not in args:
            raise ScanIncomplete("missing replacement content")
        value = args.get("ReplacementContent")
        if not isinstance(value, str):
            raise ScanIncomplete("invalid replacement content")
        return _bounded_join([value])
    if name == "multi_replace_file_content":
        chunks = args.get("ReplacementChunks")
        if not isinstance(chunks, list):
            raise ScanIncomplete("invalid replacement chunks")
        replacements: List[str] = []
        for chunk in chunks:
            if not isinstance(chunk, dict):
                raise ScanIncomplete("invalid replacement chunk")
            if "ReplacementContent" not in chunk:
                raise ScanIncomplete("missing replacement content")
            value = chunk.get("ReplacementContent")
            if not isinstance(value, str):
                raise ScanIncomplete("invalid replacement content")
            replacements.append(value)
        return _bounded_join(replacements)
    raise ScanIncomplete("unsupported write tool")


def _has_plausible_private_key(text: str) -> bool:
    for match in _PRIVATE_KEY_BLOCK.finditer(text):
        body_lines = []
        for line in match.group(2).splitlines():
            stripped = line.strip()
            if not stripped or ":" in stripped or stripped.startswith("="):
                continue
            body_lines.append(stripped)
        encoded = "".join(body_lines)
        if len(encoded) < 64 or re.fullmatch(r"[A-Za-z0-9+/]*={0,2}", encoded) is None:
            continue
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            continue
        if len(decoded) >= 32:
            return True
    return False


def _high_confidence_category(text: str) -> Optional[str]:
    if _has_plausible_private_key(text):
        return "private key material"
    if _AWS_SECRET.search(text) or _KNOWN_TOKEN.search(text):
        return "credential material"
    return None


def _has_ambiguous_secret(text: str) -> bool:
    if _PRIVATE_KEY_HEADER.search(text) or _JWT.search(text):
        return True
    for match in _AMBIGUOUS_ASSIGNMENT.finditer(text):
        if not _SAFE_VALUE.match(match.group(1)):
            return True
    return False


def _env_paths(command: str) -> List[str]:
    paths = []
    for match in _SENSITIVE_ENV.finditer(command):
        value = match.group(0).rstrip(",:)")
        basename = re.split(r"[/\\]", value)[-1].lower()
        if basename not in _SAFE_ENV_NAMES:
            paths.append(value)
    return paths


def _normal_permission_review() -> Dict[str, str]:
    return {
        "decision": "ask",
        "reason": "DLP found no high-confidence secret; normal tool permission review still applies.",
    }


def _workspace_roots(payload: Dict[str, Any]) -> List[Path]:
    roots = payload.get("workspacePaths")
    if not isinstance(roots, list):
        return []
    result = []
    for root in roots[:16]:
        if not isinstance(root, str) or not root.strip():
            continue
        try:
            candidate = Path(root).expanduser().resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if candidate.is_dir():
            result.append(candidate)
    return result


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _command_cwd(args: Dict[str, Any], payload: Dict[str, Any]) -> Path:
    roots = _workspace_roots(payload)
    if not roots:
        raise ScanIncomplete("workspace is unavailable")
    raw_cwd = args.get("Cwd")
    try:
        cwd = (
            Path(raw_cwd).expanduser().resolve(strict=True)
            if isinstance(raw_cwd, str) and raw_cwd.strip()
            else roots[0]
        )
    except (OSError, RuntimeError):
        raise ScanIncomplete("command directory is unavailable")
    if not cwd.is_dir() or not any(_within(cwd, root) for root in roots):
        raise ScanIncomplete("command directory is outside the workspace")
    return cwd


def _resolved_root(path: Path) -> Optional[Path]:
    try:
        return path.expanduser().resolve(strict=False)
    except (OSError, RuntimeError):
        return None


def _untrusted_roots(
    payload: Optional[Dict[str, Any]] = None,
    cwd: Optional[Path] = None,
    workspace_roots: Sequence[Path] = (),
) -> List[Path]:
    candidates: List[Path] = list(workspace_roots)
    if payload is not None:
        candidates.extend(_workspace_roots(payload))
        artifact = payload.get("artifactDirectoryPath")
        if isinstance(artifact, str) and artifact.strip():
            candidates.append(Path(artifact))
    if cwd is not None:
        candidates.append(cwd)
    temp_values = [
        tempfile.gettempdir(),
        os.environ.get("TMPDIR", ""),
        os.environ.get("TEMP", ""),
        os.environ.get("TMP", ""),
    ]
    if os.name != "nt":
        temp_values.extend(("/tmp", "/var/tmp", "/private/tmp"))
    candidates.extend(Path(value) for value in temp_values if value)

    result: List[Path] = []
    for candidate in candidates:
        resolved = _resolved_root(candidate)
        if resolved is not None and resolved not in result:
            result.append(resolved)
    return result


def _permissions_are_trusted(path: Path) -> bool:
    if os.name == "nt":
        return True
    for candidate in (path,) + tuple(path.parents):
        try:
            mode = candidate.stat().st_mode
        except OSError:
            return False
        if mode & (stat.S_IWGRP | stat.S_IWOTH):
            return False
    return True


def _trusted_executable(
    command: str,
    forbidden_roots: Sequence[Path],
    cwd: Optional[Path] = None,
) -> Optional[str]:
    raw = Path(command).expanduser()
    if raw.is_absolute():
        located: Optional[str] = str(raw)
    elif raw.parent != Path("."):
        located = str((cwd / raw) if cwd is not None else raw)
    else:
        located = shutil.which(command)
    if not located:
        return None
    try:
        resolved = Path(located).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    try:
        if not stat.S_ISREG(resolved.stat().st_mode):
            return None
    except OSError:
        return None
    if any(_within(resolved, root) for root in forbidden_roots):
        return None
    if not _permissions_are_trusted(resolved):
        return None
    return str(resolved)


def _run_git(
    args: Sequence[str],
    cwd: Path,
    roots: Sequence[Path],
    command: str = "git",
) -> bytes:
    git = _trusted_executable(command, roots, cwd)
    if not git:
        raise ScanIncomplete("trusted git is unavailable")
    try:
        with tempfile.TemporaryFile() as output:
            result = subprocess.run(
                [git, "-c", "core.hooksPath=/dev/null"] + list(args),
                cwd=str(cwd),
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.DEVNULL,
                timeout=COMMAND_TIMEOUT_SECONDS,
                check=False,
            )
            output.seek(0)
            captured = output.read(MAX_GIT_OUTPUT_BYTES + 1)
    except (OSError, subprocess.SubprocessError):
        raise ScanIncomplete("git inspection failed")
    if result.returncode != 0 or len(captured) > MAX_GIT_OUTPUT_BYTES:
        raise ScanIncomplete("git inspection was incomplete")
    return captured


def _shell_segments(command: str) -> List[List[str]]:
    segments: List[List[str]] = []
    current_segment: List[str] = []
    current_token: List[str] = []
    quote = ""
    index = 0

    def finish_token() -> None:
        if current_token:
            current_segment.append("".join(current_token))
            current_token[:] = []

    def finish_segment() -> None:
        finish_token()
        if current_segment:
            segments.append(list(current_segment))
            current_segment[:] = []

    while index < len(command):
        character = command[index]
        if quote:
            if character == quote:
                quote = ""
            elif character == "\\" and index + 1 < len(command) and command[index + 1] in {quote, "\\"}:
                index += 1
                current_token.append(command[index])
            else:
                current_token.append(character)
        elif character in {"'", '"'}:
            quote = character
        elif character.isspace():
            finish_token()
        elif character in ";|&()":
            finish_segment()
        elif character == "\\" and index + 1 < len(command) and command[index + 1].isspace():
            index += 1
            current_token.append(command[index])
        else:
            current_token.append(character)
        index += 1
    finish_segment()
    return segments


def _executable_basename(value: str) -> str:
    basename = re.split(r"[/\\]", value.strip('"'))[-1].lower()
    for suffix in (".exe", ".cmd", ".bat", ".com"):
        if basename.endswith(suffix):
            return basename[:-len(suffix)]
    return basename


def _command_invocations(
    command: str,
) -> List[Tuple[str, List[str], List[str], bool]]:
    invocations: List[Tuple[str, List[str], List[str], bool]] = []
    for segment in _shell_segments(command):
        index = 0
        assignments: List[str] = []
        opaque = False
        while index < len(segment) and re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*=.*", segment[index]
        ):
            assignments.append(segment[index])
            index += 1
        while index < len(segment):
            wrapper = _executable_basename(segment[index])
            if wrapper in {"command", "exec"}:
                index += 1
                continue
            if wrapper != "env":
                break
            index += 1
            while index < len(segment):
                value = segment[index]
                lowered = value.lower()
                if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", value):
                    assignments.append(value)
                    index += 1
                    continue
                if value == "--":
                    index += 1
                    break
                if lowered in {"-i", "--ignore-environment", "-0", "--null", "--debug"}:
                    opaque = True
                    index += 1
                    continue
                if lowered in {"-u", "--unset", "-c", "--chdir"}:
                    opaque = True
                    index += 2
                    continue
                if lowered.startswith(("--unset=", "--chdir=")):
                    opaque = True
                    index += 1
                    continue
                if lowered in {"-s", "--split-string"} or lowered.startswith("--split-string="):
                    opaque = True
                    index = len(segment)
                    break
                if value.startswith("-"):
                    opaque = True
                    index += 1
                    continue
                break
        if index < len(segment):
            invocations.append(
                (segment[index], segment[index + 1:], assignments, opaque)
            )
        elif segment:
            invocations.append((segment[0], segment[1:], assignments, True))
    return invocations


def _git_invocations(
    command: str,
) -> List[Tuple[str, List[str], List[str], bool]]:
    return [
        (executable, args, assignments, opaque)
        for executable, args, assignments, opaque in _command_invocations(command)
        if _executable_basename(executable) == "git"
    ]


def _has_git_operation(command: str, operations: Sequence[str]) -> bool:
    expected = {operation.lower() for operation in operations}
    return any(
        any(argument.lower() in expected for argument in args)
        for _, args, _, _ in _git_invocations(command)
    )


def _has_executable(command: str, names: Sequence[str]) -> bool:
    expected = {name.lower() for name in names}
    return any(
        not opaque and _executable_basename(executable) in expected
        for executable, _, _, opaque in _command_invocations(command)
    )


def _arguments_may_invoke_git_commit(arguments: Sequence[str]) -> bool:
    joined = " ".join(arguments)
    return re.search(
        r"(?i)(?:^|[\s/\\])git(?:\.exe)?(?:\s+[^;&|]*)?\s+commit(?:\s|$)",
        joined,
    ) is not None


def _opaque_wrapper_requires_review(command: str, has_env_paths: bool) -> bool:
    nested_or_privileged = {
        "sudo", "doas", "sh", "bash", "dash", "zsh", "fish", "nu",
        "pwsh", "powershell", "cmd",
    }
    for executable, args, _, opaque in _command_invocations(command):
        basename = _executable_basename(executable)
        may_commit = _arguments_may_invoke_git_commit(args)
        if opaque and (has_env_paths or may_commit or basename == "git"):
            return True
        if basename in nested_or_privileged and (has_env_paths or may_commit):
            return True
        if basename not in {"git", "env", "command", "exec"} and may_commit:
            return True
    return False


def _commit_has_git_environment(command: str) -> bool:
    for _, args, assignments, opaque in _git_invocations(command):
        if not any(argument.lower() == "commit" for argument in args):
            continue
        if opaque:
            return True
        for assignment in assignments:
            name = assignment.split("=", 1)[0].upper()
            if name.startswith("GIT_"):
                return True
    return False


def _commit_tokens(command: str) -> Optional[List[str]]:
    for _, args, _, _ in _git_invocations(command):
        for index, argument in enumerate(args):
            if argument.lower() == "commit":
                return args[index + 1:]
    return None


def _commit_executable(command: str) -> Optional[str]:
    for executable, args, _, _ in _git_invocations(command):
        if any(argument.lower() == "commit" for argument in args):
            return executable
    return None


def _commit_changes_prospective_tree(command: str) -> bool:
    tokens = _commit_tokens(command)
    if tokens is None:
        return True
    value_options = {
        "-m", "--message", "-F", "--file", "-C", "--reuse-message",
        "-c", "--reedit-message", "--fixup", "--squash", "--author",
        "--date", "--cleanup", "-t", "--template", "--trailer", "-S",
        "--gpg-sign",
    }
    consume_value = False
    for index, token in enumerate(tokens):
        if consume_value:
            consume_value = False
            continue
        lowered = token.lower()
        if token == "--":
            return index + 1 < len(tokens)
        if lowered in _GIT_COMMIT_TREE_MODES:
            return True
        if any(lowered.startswith(option + "=") for option in _GIT_COMMIT_TREE_MODES):
            return True
        if token.startswith("--"):
            if "=" not in token and token in value_options:
                consume_value = True
            continue
        if token.startswith("-") and token != "-":
            short = token[1:]
            for flag in short:
                if flag in {"a", "i", "o", "p"}:
                    return True
                if flag in {"m", "F", "C", "c", "S", "t"}:
                    if len(short) == 1:
                        consume_value = True
                    break
            continue
        return True
    return False


def _inspect_staged_commit(args: Dict[str, Any], payload: Dict[str, Any], command: str) -> str:
    if re.search(r"(?i)(?:^|\s)(?:-C|--git-dir|--work-tree)(?:\s|=)", command):
        return "ask"
    if (
        _has_git_operation(command, ("add",))
        or _GIT_COMMIT_ALL.search(command)
        or _commit_changes_prospective_tree(command)
    ):
        return "ask"

    cwd = _command_cwd(args, payload)
    roots = _untrusted_roots(payload, cwd)
    git_command = _commit_executable(command)
    if git_command is None:
        return "ask"
    names = _run_git(
        ["diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR", "--"],
        cwd,
        roots,
        git_command,
    )
    for raw_name in names.split(b"\0"):
        name = raw_name.decode("utf-8", "replace")
        if _env_paths(name):
            return "deny"

    diff = _run_git(
        ["diff", "--cached", "--no-ext-diff", "--no-textconv", "--unified=0", "--"],
        cwd,
        roots,
        git_command,
    ).decode("utf-8", "replace")
    additions = "\n".join(
        line[1:]
        for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )
    if _high_confidence_category(additions):
        return "deny"
    if _has_ambiguous_secret(additions):
        return "ask"
    return "pass"


def _security_decision(payload: Dict[str, Any]) -> Dict[str, str]:
    name, args = _tool_call(payload)
    if name in WRITE_TOOLS:
        content = _write_content(name, args)
        category = _high_confidence_category(content)
        if category:
            return {"decision": "deny", "reason": "DLP blocked high-confidence %s." % category}
        if _has_ambiguous_secret(content):
            return {
                "decision": "force_ask",
                "reason": "DLP found possible credential material; review the destination and content before proceeding.",
            }
        return _normal_permission_review()

    if name != "run_command":
        raise ScanIncomplete("unsupported tool")
    command = args.get("CommandLine")
    if not isinstance(command, str) or len(command) > MAX_SCAN_CHARS:
        raise ScanIncomplete("invalid command")

    category = _high_confidence_category(command)
    if category:
        return {"decision": "deny", "reason": "DLP blocked high-confidence %s." % category}

    env_paths = _env_paths(command)
    if _opaque_wrapper_requires_review(command, bool(env_paths)):
        return {
            "decision": "force_ask",
            "reason": "DLP cannot safely inspect this wrapped command; explicit review is required.",
        }
    if _commit_has_git_environment(command):
        return {
            "decision": "force_ask",
            "reason": "DLP cannot staged-inspect a commit whose Git environment changes repository or index behavior.",
        }
    if env_paths and (
        _has_git_operation(command, ("add", "commit", "show", "diff"))
        or _has_executable(command, _ENV_EGRESS_EXECUTABLES)
        or _SCRIPT_ENV_OUTPUT.search(command)
    ):
        return {
            "decision": "deny",
            "reason": "DLP blocked an explicit attempt to commit, print, or transmit a sensitive environment file.",
        }
    if env_paths:
        return {
            "decision": "force_ask",
            "reason": "DLP found a sensitive environment-file reference; review how the command will use it.",
        }

    if _has_git_operation(command, ("commit",)):
        staged = _inspect_staged_commit(args, payload, command)
        if staged == "deny":
            return {
                "decision": "deny",
                "reason": "DLP blocked a commit containing high-confidence secret material or a sensitive environment file.",
            }
        if staged == "ask":
            return {
                "decision": "force_ask",
                "reason": "DLP could not safely validate all content that this commit may stage; review it before proceeding.",
            }

    if _has_ambiguous_secret(command):
        return {
            "decision": "force_ask",
            "reason": "DLP found possible credential material in the command; review it before proceeding.",
        }
    return _normal_permission_review()


def _read_small(path: Path) -> Optional[str]:
    try:
        if not path.is_file() or path.stat().st_size > MAX_MANIFEST_BYTES:
            return None
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def _package_manifest(root: Path) -> Optional[Dict[str, Any]]:
    text = _read_small(root / "package.json")
    if text is None:
        return None
    try:
        package = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(package, dict):
        return None
    return package


def _package_dependencies(root: Path) -> Dict[str, Any]:
    package = _package_manifest(root)
    if package is None:
        return {}
    result: Dict[str, Any] = {}
    for field in ("dependencies", "devDependencies", "peerDependencies"):
        values = package.get(field)
        if isinstance(values, dict):
            for key in values:
                if isinstance(key, str):
                    result[key.lower()] = True
    return result


def _package_manager(root: Path) -> str:
    if (root / "pnpm-workspace.yaml").is_file() or (root / "pnpm-lock.yaml").is_file():
        return "pnpm"
    if (root / "yarn.lock").is_file():
        return "yarn"
    if any((root / name).is_file() for name in ("bun.lock", "bun.lockb")):
        return "bun"
    return "npm"


def _allowed_check_name(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    return value if value.casefold() in _CHECK_NAMES else None


def _make_targets(root: Path) -> List[str]:
    text = _read_small(root / "Makefile")
    if text is None:
        text = _read_small(root / "makefile")
    if text is None:
        return []
    targets: List[str] = []
    for match in re.finditer(r"(?m)^([A-Za-z0-9][A-Za-z0-9._-]{0,63})\s*:(?!=)", text):
        target = _allowed_check_name(match.group(1))
        if target is not None:
            targets.append("make %s" % target)
    return targets


def _project_blueprint(root: Path) -> Tuple[List[str], List[str]]:
    """Return sanitized topology labels and candidate commands.

    Manifest values and build recipes are untrusted input. Only fixed labels and
    allowlisted, shell-safe script/target names are emitted into model context.
    """
    topology: List[str] = []
    checks: List[str] = []
    package = _package_manifest(root)
    manager = _package_manager(root)
    if (root / "pnpm-workspace.yaml").is_file():
        topology.append("pnpm workspace")
    if (root / "lerna.json").is_file():
        topology.append("Lerna workspace")
    if package is not None:
        workspaces = package.get("workspaces")
        if isinstance(workspaces, (list, dict)) and not (
            manager == "pnpm" and "pnpm workspace" in topology
        ):
            topology.append("%s workspace" % manager)
        scripts = package.get("scripts")
        if isinstance(scripts, dict):
            for name in scripts:
                allowed = _allowed_check_name(name)
                if allowed is not None:
                    checks.append("%s run %s" % (manager, allowed))

    go_work = _read_small(root / "go.work")
    if go_work is not None:
        topology.append("Go workspace")
    if go_work is not None or _read_small(root / "go.mod") is not None:
        checks.append("go test ./...")

    cargo = _read_small(root / "Cargo.toml")
    if cargo is not None:
        if re.search(r"(?m)^\s*\[workspace\]\s*(?:#.*)?$", cargo):
            topology.append("Cargo workspace")
        checks.append("cargo test")

    pyproject = _read_small(root / "pyproject.toml")
    if (root / "pytest.ini").is_file() or (
        pyproject is not None
        and re.search(r"(?m)^\s*\[tool\.pytest(?:\.|\])", pyproject)
    ):
        checks.append("python -m pytest")
    checks.extend(_make_targets(root))
    return list(dict.fromkeys(topology)), list(dict.fromkeys(checks))


def _detect_root(root: Path) -> Tuple[List[str], List[Tuple[str, Sequence[str]]]]:
    stacks: List[str] = []
    runtimes: List[Tuple[str, Sequence[str]]] = []
    package = _package_manifest(root)
    dependencies = _package_dependencies(root)
    if package is not None:
        runtimes.append(("Node", ("node", "--version")))
        for dependency, label in (
            ("next", "Next.js"), ("react", "React"), ("vite", "Vite"),
            ("express", "Express"), ("@nestjs/core", "NestJS"),
        ):
            if dependency in dependencies:
                stacks.append(label)

    pyproject = _read_small(root / "pyproject.toml")
    requirements = _read_small(root / "requirements.txt")
    python_text = "\n".join(value for value in (pyproject, requirements) if value)
    if python_text:
        runtimes.append(("Python", (sys.executable, "--version")))
        lower = python_text.lower()
        for marker, label in (
            ("fastapi", "FastAPI"), ("django", "Django"), ("flask", "Flask"),
        ):
            if re.search(r"(?<![a-z0-9_-])%s(?![a-z0-9_-])" % marker, lower):
                stacks.append(label)

    go_mod = _read_small(root / "go.mod")
    go_work = _read_small(root / "go.work")
    if go_mod is not None or go_work is not None:
        runtimes.append(("Go", ("go", "version")))
        if go_mod is not None and "github.com/gin-gonic/gin" in go_mod:
            stacks.append("Gin")

    cargo = _read_small(root / "Cargo.toml")
    if cargo is not None:
        runtimes.append(("Rust", ("rustc", "--version")))
        if re.search(r"(?m)^\s*axum\s*=", cargo):
            stacks.append("Axum")
    return stacks, runtimes


def _runtime_version(
    label: str,
    command: Sequence[str],
    roots: Sequence[Path],
) -> Optional[str]:
    executable = _trusted_executable(command[0], roots)
    if not executable:
        return None
    actual = [executable] + list(command[1:])
    try:
        with tempfile.TemporaryFile() as output:
            result = subprocess.run(
                actual,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                timeout=1.0,
                check=False,
            )
            output.seek(0)
            captured = output.read(4097)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or len(captured) > 4096:
        return None
    decoded = captured.decode("utf-8", "replace")
    line = decoded.splitlines()[0][:256] if decoded else ""
    patterns = {
        "Node": re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?$"),
        "Python": re.compile(r"^Python [0-9]+\.[0-9]+\.[0-9]+(?:[A-Za-z0-9.+-]*)?$"),
        "Go": re.compile(r"^go version (go[0-9]+\.[0-9]+(?:\.[0-9]+)?(?:[A-Za-z0-9.+-]*))"),
        "Rust": re.compile(r"^rustc ([0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?)"),
    }
    match = patterns[label].match(line.strip())
    if not match:
        return None
    return match.group(1) if match.lastindex else match.group(0)


def _context(payload: Dict[str, Any]) -> Dict[str, Any]:
    invocation = payload.get("invocationNum")
    if not isinstance(invocation, int) or isinstance(invocation, bool) or invocation != 0:
        return {}
    _cleanup_stale_format_locks()
    roots = _workspace_roots(payload)
    if not roots:
        return {}

    stacks: List[str] = []
    runtime_specs: List[Tuple[str, Sequence[str]]] = []
    topology: List[str] = []
    checks: List[str] = []
    for root in roots[:4]:
        found_stacks, found_runtimes = _detect_root(root)
        found_topology, found_checks = _project_blueprint(root)
        stacks.extend(found_stacks)
        runtime_specs.extend(found_runtimes)
        topology.extend(found_topology)
        checks.extend(found_checks)
    stacks = list(dict.fromkeys(stacks))
    runtime_specs = list(dict((label, command) for label, command in runtime_specs).items())
    topology = list(dict.fromkeys(topology))
    checks = list(dict.fromkeys(checks))
    if not stacks and not runtime_specs and not topology and not checks:
        return {}

    runtime_values = []
    forbidden_executable_roots = _untrusted_roots(payload)
    for label, command in runtime_specs[:4]:
        version = _runtime_version(label, command, forbidden_executable_roots)
        if version:
            runtime_values.append("%s: %s" % (label, version))
    if not stacks and not runtime_values and not topology and not checks:
        return {}
    parts = ["Detected project context (advisory; static manifests and local runtime versions)."]
    if stacks:
        parts.append("Frameworks: %s." % ", ".join(stacks[:12]))
    if runtime_values:
        parts.append("Runtimes: %s." % "; ".join(runtime_values))
    if topology:
        parts.append("Topology: %s." % ", ".join(topology[:8]))
    if checks:
        parts.append(
            "Candidate checks (inspect project config before running): %s."
            % "; ".join("`%s`" % command for command in checks[:10])
        )
    message = " ".join(parts)
    encoded = message.encode("utf-8")
    if len(encoded) > MAX_CONTEXT_BYTES:
        message = encoded[:MAX_CONTEXT_BYTES].decode("utf-8", "ignore")
    return {"injectSteps": [{"ephemeralMessage": message}]}


def _configured_prettier(directory: Path, root: Path) -> bool:
    current = directory
    for _ in range(64):
        if not _within(current, root):
            break
        if any((current / name).is_file() for name in _PRETTIER_CONFIGS):
            return True
        package_text = _read_small(current / "package.json")
        if package_text is not None:
            try:
                package = json.loads(package_text)
                if isinstance(package, dict) and "prettier" in package:
                    return True
            except (ValueError, TypeError):
                pass
        if current == root:
            break
        current = current.parent
    return False


def _python_config(root: Path, section: str) -> bool:
    if section == "ruff" and any(
        (root / name).is_file() for name in ("ruff.toml", ".ruff.toml")
    ):
        return True
    text = _read_small(root / "pyproject.toml")
    return text is not None and re.search(r"(?m)^\s*\[tool\.%s(?:\.|\])" % section, text) is not None


def _local_executable(root: Path, name: str) -> Optional[str]:
    candidates = (
        root / ".venv" / "bin" / name,
        root / "venv" / "bin" / name,
        root / ".venv" / "Scripts" / (name + ".exe"),
        root / "venv" / "Scripts" / (name + ".exe"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def _formatter(
    path: Path,
    root: Path,
    forbidden_roots: Optional[Sequence[Path]] = None,
) -> Optional[List[str]]:
    restrictions = list(forbidden_roots or _untrusted_roots(workspace_roots=(root,)))
    suffix = path.suffix.lower()
    if suffix in _PRETTIER_EXTENSIONS and _configured_prettier(path.parent, root):
        current = path.parent
        for _ in range(64):
            if not _within(current, root):
                break
            binary = current / "node_modules" / ".bin" / ("prettier.cmd" if os.name == "nt" else "prettier")
            if binary.is_file():
                return [str(binary), "--write", str(path)]
            if current == root:
                break
            current = current.parent
    if suffix == ".py":
        if _python_config(root, "ruff"):
            binary = _local_executable(root, "ruff") or _trusted_executable(
                "ruff", restrictions
            )
            if binary:
                return [binary, "format", str(path)]
        if _python_config(root, "black"):
            binary = _local_executable(root, "black") or _trusted_executable(
                "black", restrictions
            )
            if binary:
                return [binary, "--quiet", str(path)]
    if suffix == ".go":
        binary = _trusted_executable("gofmt", restrictions)
        if binary:
            return [binary, "-w", str(path)]
    return None


def _acquire_file_lock(handle: Any, wait_seconds: float) -> bool:
    if os.name == "nt":
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (BlockingIOError, OSError):
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.01)


def _release_file_lock(handle: Any) -> None:
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


def _private_format_lock_directory(
    temp_root: Optional[Path] = None,
) -> Optional[Path]:
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
    directory = base / (FORMAT_LOCK_DIRECTORY_PREFIX + identity)
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


def _open_lock_file(path: Path, create: bool = True) -> Any:
    flags = os.O_RDWR
    if create:
        flags |= os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if path.is_symlink():
        raise OSError("lock path must not be a symlink")
    descriptor = os.open(str(path), flags, 0o600)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise OSError("lock path must be a regular single-link file")
        if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
            raise OSError("lock file must be owned by the current user")
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
        return os.fdopen(descriptor, "r+b", buffering=0)
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


def _cleanup_stale_format_locks(
    temp_dir: Optional[Path] = None,
    now: Optional[float] = None,
) -> None:
    directory = temp_dir or _private_format_lock_directory()
    if directory is None:
        return
    cutoff = (time.time() if now is None else now) - FORMAT_LOCK_TTL_SECONDS
    try:
        candidates = itertools.islice(
            directory.glob("%s*.lock" % FORMAT_LOCK_PREFIX),
            256,
        )
    except OSError:
        return
    try:
        for candidate in candidates:
            if _FORMAT_LOCK_NAME.fullmatch(candidate.name) is None:
                continue
            try:
                metadata = candidate.lstat()
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_mtime >= cutoff:
                    continue
                handle = _open_lock_file(candidate, create=False)
            except OSError:
                continue
            acquired = False
            delete_after_close = False
            try:
                acquired = _acquire_file_lock(handle, 0.0)
                if (
                    acquired
                    and _open_file_matches_path(handle, candidate)
                    and candidate.lstat().st_mtime < cutoff
                ):
                    if os.name == "nt":
                        delete_after_close = True
                    else:
                        candidate.unlink()
            except (FileNotFoundError, OSError):
                pass
            finally:
                if acquired:
                    _release_file_lock(handle)
                handle.close()
            if delete_after_close:
                try:
                    candidate.unlink()
                except (FileNotFoundError, OSError):
                    pass
    except OSError:
        return


def _format_lock_path(path: Path, temp_dir: Optional[Path] = None) -> Path:
    digest = hashlib.sha256(str(path).encode("utf-8", "replace")).hexdigest()[:24]
    directory = temp_dir or _private_format_lock_directory()
    if directory is None:
        raise OSError("private formatter lock directory is unavailable")
    return directory / ("%s%s.lock" % (FORMAT_LOCK_PREFIX, digest))


@contextmanager
def _format_lock(path: Path) -> Iterator[bool]:
    try:
        lock_path = _format_lock_path(path)
        handle = _open_lock_file(lock_path)
    except OSError:
        yield False
        return
    acquired = False
    try:
        acquired = _acquire_file_lock(handle, LOCK_WAIT_SECONDS)
        if acquired and not _open_file_matches_path(handle, lock_path):
            _release_file_lock(handle)
            acquired = False
        if acquired:
            try:
                os.utime(str(lock_path), None)
            except OSError:
                pass
        yield acquired
    finally:
        if acquired:
            _release_file_lock(handle)
        handle.close()


def _format(payload: Dict[str, Any]) -> Dict[str, Any]:
    if os.environ.get("HARNESS_AUTO_FORMAT") != "1" or payload.get("error"):
        return {}
    _cleanup_stale_format_locks()
    name, args = _tool_call(payload)
    if name not in WRITE_TOOLS:
        return {}
    target = args.get("TargetFile")
    if not isinstance(target, str) or not target.strip():
        return {}
    roots = _workspace_roots(payload)
    try:
        path = Path(target).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        return {}
    if not path.is_file():
        return {}
    root = next((candidate for candidate in roots if _within(path, candidate)), None)
    if root is None:
        return {}
    command = _formatter(path, root, _untrusted_roots(payload, root))
    if not command:
        return {}
    with _format_lock(path) as acquired:
        if not acquired:
            return {}
        try:
            subprocess.run(
                command,
                cwd=str(root),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=FORMAT_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            pass
    return {}


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        payload = _read_payload()
        if mode == "security":
            _emit(_security_decision(payload))
        elif mode == "context":
            _emit(_context(payload))
        elif mode == "format":
            _emit(_format(payload))
        else:
            _emit({})
    except Exception:
        if mode == "security":
            _emit(
                {
                    "decision": "force_ask",
                    "reason": "DLP could not safely inspect this operation; explicit review is required.",
                }
            )
        else:
            _emit({})


if __name__ == "__main__":
    main()
