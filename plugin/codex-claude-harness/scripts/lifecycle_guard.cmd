:; case "$0" in */*) script_path="$0" ;; *) script_path="./$0" ;; esac
:; script_dir=$(CDPATH= cd -- "${script_path%/*}" && pwd -P)
:; python_runtime=""
:; if [ -f "$script_dir/.python-runtime" ]; then IFS= read -r python_runtime < "$script_dir/.python-runtime" || python_runtime=""; fi
:; case "$python_runtime" in /*) if [ -f "$python_runtime" ] && [ -x "$python_runtime" ]; then exec "$python_runtime" "$script_dir/lifecycle_guard.py" "$1"; fi ;; esac
:; if [ "$1" = "security" ]; then printf '%s\n' '{"decision":"force_ask","reason":"DLP is unavailable because Python 3.8 or newer is not installed; explicit review is required."}'; else printf '%s\n' '{}'; fi
:; exit 0
@echo off
setlocal
set "system_powershell=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
set "harness_python_marker=%~dp0.python-runtime"
set "harness_python_script=%~dp0lifecycle_guard.py"
set "harness_python_mode=%~1"
if exist "%system_powershell%" if exist "%~dp0.python-runtime" (
  "%system_powershell%" -NoLogo -NoProfile -NonInteractive -Command "$e=New-Object System.Text.UTF8Encoding($false,$true); try {$p=[IO.File]::ReadAllText($env:harness_python_marker,$e).Trim()} catch {exit 1}; if (![IO.Path]::IsPathRooted($p) -or !(Test-Path -LiteralPath $p -PathType Leaf)) {exit 1}; & $p $env:harness_python_script $env:harness_python_mode; exit $LASTEXITCODE"
  if not errorlevel 1 exit /b 0
)
if /I "%~1"=="security" (
  echo {"decision":"force_ask","reason":"DLP is unavailable because Python 3.8 or newer is not installed; explicit review is required."}
) else (
  echo {}
)
exit /b 0
