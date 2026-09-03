#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
model="${HARNESS_EVAL_MODEL:-gemini-3.7-flash-high}"
case_filter="${HARNESS_EVAL_CASE:-}"
cases_path="${repo_root}/evals/cases.json"
max_continuations=3

print_response_diagnostic() {
  if ! python3 - "$1" <<'PY' >&2
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
raw = path.read_text(encoding="utf-8", errors="replace")
try:
    payload = json.loads(raw)
except json.JSONDecodeError:
    print(raw[:2000])
else:
    detail = payload.get("error") or payload.get("response", "")
    print(f"[agy] status={payload.get('status')}: {str(detail)[:2000]}")
PY
  then
    printf '[agy] response diagnostics were unreadable\n' >&2
  fi
}

response_has_harness() {
  python3 - "$1" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    response = json.load(handle)
raise SystemExit(0 if "Harness:" in response.get("response", "") else 1)
PY
}

if ! command -v agy >/dev/null 2>&1; then
  printf 'agy is required to run harness smoke evals.\n' >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  printf 'python3 is required to parse eval cases.\n' >&2
  exit 1
fi

eval_root="$(mktemp -d "${repo_root}/.harness-eval.XXXXXX")"
empty_hooks="${eval_root}/empty-hooks"
mkdir -p -- "${empty_hooks}"
cleanup() {
  rm -rf -- "${eval_root}"
}
trap cleanup EXIT

case_count="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1], encoding="utf-8"))))' "${cases_path}")"
failures=0
executed=0
selected=0
skipped=0

for ((case_index = 0; case_index < case_count; case_index += 1)); do
  case_id="$(python3 - "${cases_path}" "${case_index}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    case = json.load(handle)[int(sys.argv[2])]
print(case["id"])
PY
  )"
  if [[ -n "${case_filter}" && "${case_id}" != "${case_filter}" ]]; then
    continue
  fi
  selected=$((selected + 1))
  fixture="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))[int(sys.argv[2])]["fixture"])' "${cases_path}" "${case_index}")"
  prompt="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))[int(sys.argv[2])]["prompt"])' "${cases_path}" "${case_index}")"
  route="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))[int(sys.argv[2])]["route"])' "${cases_path}" "${case_index}")"
  expect_change="$(python3 -c 'import json,sys; print(str(json.load(open(sys.argv[1], encoding="utf-8"))[int(sys.argv[2])]["expect_change"]).lower())' "${cases_path}" "${case_index}")"
  expect_response_json="$(python3 -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1], encoding="utf-8"))[int(sys.argv[2])].get("response_contains", [])))' "${cases_path}" "${case_index}")"
  reject_response_json="$(python3 -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1], encoding="utf-8"))[int(sys.argv[2])].get("response_not_contains", [])))' "${cases_path}" "${case_index}")"
  only_response_lines_json="$(python3 -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1], encoding="utf-8"))[int(sys.argv[2])].get("response_only_lines", [])))' "${cases_path}" "${case_index}")"
  response_line_count_json="$(python3 -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1], encoding="utf-8"))[int(sys.argv[2])].get("response_line_count")))' "${cases_path}" "${case_index}")"
  required_changed_paths_json="$(python3 -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1], encoding="utf-8"))[int(sys.argv[2])].get("required_changed_paths", [])))' "${cases_path}" "${case_index}")"
  allowed_changed_paths_json="$(python3 -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1], encoding="utf-8"))[int(sys.argv[2])]["allowed_changed_paths"]))' "${cases_path}" "${case_index}")"
  requires_json="$(python3 -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1], encoding="utf-8"))[int(sys.argv[2])].get("requires", [])))' "${cases_path}" "${case_index}")"
  verify_json="$(python3 -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1], encoding="utf-8"))[int(sys.argv[2])]["verify"]))' "${cases_path}" "${case_index}")"
  acceptance_criteria_json="$(python3 -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1], encoding="utf-8"))[int(sys.argv[2])].get("acceptance_criteria", [])))' "${cases_path}" "${case_index}")"
  case_dir="${eval_root}/${case_id}"
  response_path="${eval_root}/${case_id}.json"

  missing_requirements=()
  while IFS= read -r requirement; do
    if [[ -n "${requirement}" ]] && ! command -v "${requirement}" >/dev/null 2>&1; then
      missing_requirements+=("${requirement}")
    fi
  done < <(python3 -c 'import json,sys; print("\n".join(json.loads(sys.argv[1])))' "${requires_json}")
  if ((${#missing_requirements[@]} > 0)); then
    printf '[skip] %s: missing required runtime(s): %s\n' "${case_id}" "${missing_requirements[*]}"
    skipped=$((skipped + 1))
    continue
  fi
  executed=$((executed + 1))

  cp -R "${repo_root}/evals/fixtures/${fixture}" "${case_dir}"
  git -C "${case_dir}" init -q
  git -C "${case_dir}" config user.name 'Harness Eval'
  git -C "${case_dir}" config user.email 'harness-eval@example.invalid'
  git -C "${case_dir}" config commit.gpgsign false
  git -C "${case_dir}" config core.hooksPath "${empty_hooks}"
  git -C "${case_dir}" add .
  git -C "${case_dir}" commit -qm baseline

  printf '[eval] %s (%s)\n' "${case_id}" "${model}"
  if ! (
    cd "${case_dir}"
    agy -p "${prompt}" --model "${model}" \
      --new-project --add-dir "${case_dir}" --sandbox --mode=accept-edits \
      --output-format json --print-timeout 15m
  ) > "${response_path}"; then
    printf '[fail] %s: agy exited non-zero\n' "${case_id}" >&2
    print_response_diagnostic "${response_path}"
    failures=$((failures + 1))
    continue
  fi

  if ! conversation_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["conversation_id"])' "${response_path}")"; then
    printf '[fail] %s: response has no conversation ID\n' "${case_id}" >&2
    print_response_diagnostic "${response_path}"
    failures=$((failures + 1))
    continue
  fi

  continuation_failed=false
  for ((attempt = 1; attempt <= max_continuations; attempt += 1)); do
    if response_has_harness "${response_path}"; then
      break
    fi
    sleep 5
    if ! (
      cd "${case_dir}"
      agy -p 'Continue the pending work, collect all required subagent results, and finish the response with a Harness status line.' \
        --conversation "${conversation_id}" --model "${model}" \
        --add-dir "${case_dir}" --sandbox --mode=accept-edits \
        --output-format json --print-timeout 15m
    ) > "${response_path}"; then
      printf '[fail] %s: continuation %d exited non-zero\n' "${case_id}" "${attempt}" >&2
      print_response_diagnostic "${response_path}"
      continuation_failed=true
      break
    fi
  done

  if [[ "${continuation_failed}" == "true" ]]; then
    failures=$((failures + 1))
    continue
  fi

  if ! python3 - "${response_path}" "${expect_response_json}" "${reject_response_json}" "${only_response_lines_json}" "${route}" "${response_line_count_json}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    response = json.load(handle)
if response.get("status") != "SUCCESS":
    raise SystemExit(f"unexpected status: {response.get('status')}")
text = response.get("response", "")
if "Harness:" not in text:
    raise SystemExit("missing Harness status line")
expected_route = sys.argv[5]
reported_routes = [
    line.strip().partition(":")[2].split(";", 1)[0].strip()
    for line in text.splitlines()
    if line.strip().startswith("Harness:")
]
if expected_route not in reported_routes:
    raise SystemExit(f"Harness status line does not name route {expected_route}")
missing = [term for term in json.loads(sys.argv[2]) if term not in text]
if missing:
    raise SystemExit(f"missing expected response terms: {missing}")
folded_text = text.casefold()
forbidden = [
    term for term in json.loads(sys.argv[3])
    if term.casefold() in folded_text
]
if forbidden:
    raise SystemExit(f"response contains forbidden terms: {forbidden}")
only_lines = json.loads(sys.argv[4])
if only_lines:
    nonblank = [line.strip() for line in text.splitlines() if line.strip()]
    if nonblank != only_lines:
        raise SystemExit(f"unexpected response lines: expected exactly {only_lines}")
expected_line_count = json.loads(sys.argv[6])
if expected_line_count is not None:
    nonblank_count = len([line for line in text.splitlines() if line.strip()])
    if nonblank_count != expected_line_count:
        raise SystemExit(
            f"unexpected response line count: expected {expected_line_count}, "
            f"got {nonblank_count}"
        )
PY
  then
    printf '[fail] %s: invalid response envelope\n' "${case_id}" >&2
    print_response_diagnostic "${response_path}"
    failures=$((failures + 1))
  fi

  changed=false
  if [[ -n "$(git -C "${case_dir}" status --porcelain)" ]]; then
    changed=true
  fi
  if [[ "${changed}" != "${expect_change}" ]]; then
    printf '[fail] %s: expected change=%s, got %s\n' "${case_id}" "${expect_change}" "${changed}" >&2
    print_response_diagnostic "${response_path}"
    failures=$((failures + 1))
  fi

  if ! python3 "${repo_root}/evals/validate_changed_paths.py" \
    "${case_dir}" "${required_changed_paths_json}" "${allowed_changed_paths_json}"
  then
    printf '[fail] %s: changed-path contract failed\n' "${case_id}" >&2
    failures=$((failures + 1))
  fi

  if [[ "${verify_json}" != '[]' ]]; then
    if ! python3 - "${case_dir}" "${verify_json}" <<'PY'
import json
import subprocess
import sys

subprocess.run(json.loads(sys.argv[2]), cwd=sys.argv[1], check=True)
PY
    then
      printf '[fail] %s: deterministic verification failed\n' "${case_id}" >&2
      print_response_diagnostic "${response_path}"
      failures=$((failures + 1))
    fi
  fi

  if [[ "${acceptance_criteria_json}" != '[]' ]]; then
    if ! python3 - "${case_dir}" "${acceptance_criteria_json}" <<'PY'
import json
import subprocess
import sys

case_dir = sys.argv[1]
for criterion in json.loads(sys.argv[2]):
    print(f"[acceptance] {criterion['id']}: {criterion['description']}")
    subprocess.run(criterion["verify"], cwd=case_dir, check=True)
PY
    then
      printf '[fail] %s: acceptance criterion verification failed\n' "${case_id}" >&2
      print_response_diagnostic "${response_path}"
      failures=$((failures + 1))
    fi
  fi
done

if ((selected == 0)); then
  printf '[fail] no smoke eval case matched %s\n' "${case_filter}" >&2
  exit 1
fi

if ((executed == 0)); then
  printf '[fail] all %d selected smoke eval(s) were skipped for missing runtimes\n' "${selected}" >&2
  exit 1
fi

if ((failures > 0)); then
  printf '[fail] %d smoke eval check(s) failed\n' "${failures}" >&2
  exit 1
fi

printf '[ok] %s smoke evals passed with %s (%s skipped)\n' "${executed}" "${model}" "${skipped}"
