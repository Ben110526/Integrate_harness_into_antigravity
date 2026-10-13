#Requires -Version 5.1
<#
.SYNOPSIS
    Diagnostic health check for the harness installation (agy, plugin, pinned
    hook runtime, MCP inventory, policy). Mirrors doctor.sh.
#>
$ErrorActionPreference = "Stop"

$packageRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pluginDir = Join-Path $packageRoot "plugin/codex-claude-harness"
$readinessWarnings = 0

$agyCommand = Get-Command agy -ErrorAction SilentlyContinue
if (-not $agyCommand) {
    Write-Host "[fail] agy is not installed or not on PATH." -ForegroundColor Red
    exit 1
}
$agyExecutable = $agyCommand.Source
Write-Host "[ok] agy: $agyExecutable"
& $agyExecutable --version

$pluginList = & $agyExecutable plugin list | Out-String
if ($pluginList -notmatch '"name": "codex-claude-harness"') {
    Write-Host "[fail] codex-claude-harness is not installed. Run .\install.ps1." -ForegroundColor Red
    exit 1
}
Write-Host "[ok] codex-claude-harness is installed."

$pluginInstallDir = $null
foreach ($candidateDir in @(
    (Join-Path $HOME ".gemini/config/plugins/codex-claude-harness"),
    (Join-Path $HOME ".gemini/antigravity-cli/plugins/codex-claude-harness"))) {
    if (Test-Path $candidateDir -PathType Container) {
        $pluginInstallDir = $candidateDir
        break
    }
}
$pluginCheckDir = $pluginDir
if ($pluginInstallDir) {
    $pluginCheckDir = $pluginInstallDir
}
& $agyExecutable plugin validate $pluginCheckDir

$runtimeMarker = $null
if ($pluginInstallDir) {
    $runtimeMarker = Join-Path $pluginInstallDir "scripts/.python-runtime"
}
$pinnedPython = $null
if ($runtimeMarker -and (Test-Path $runtimeMarker -PathType Leaf)) {
    $pinnedPython = (Get-Content $runtimeMarker -Raw).Trim()
}
if (-not $pinnedPython -or -not [IO.Path]::IsPathRooted($pinnedPython) -or -not (Test-Path $pinnedPython -PathType Leaf)) {
    Write-Host "[fail] installed hook runtime marker is missing or invalid: $runtimeMarker. Rerun .\install.ps1." -ForegroundColor Red
    exit 3
}
& $pinnedPython -c 'import sys; raise SystemExit(sys.version_info < (3, 8))' 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[fail] installed hook runtime must be Python 3.8 or newer: $pinnedPython. Rerun .\install.ps1." -ForegroundColor Red
    exit 3
}
$pythonVersion = (& $pinnedPython -c 'import platform; print(platform.python_version())' 2>$null)
Write-Host "[ok] pinned lifecycle hook runtime: Python $pythonVersion ($pinnedPython)."

$mcpServers = @()
$installedMcpConfig = $null
if ($pluginInstallDir) {
    $installedMcpConfig = Join-Path $pluginInstallDir "mcp_config.json"
}
if ($installedMcpConfig -and (Test-Path $installedMcpConfig -PathType Leaf)) {
    $mcpServers = & $pinnedPython -c @'
import json
import sys

known = {
    "harness-context7",
    "harness-serena",
    "harness-playwright",
    "harness-github",
    "harness-sentry",
}
with open(sys.argv[1], encoding="utf-8") as handle:
    payload = json.load(handle)
servers = payload.get("mcpServers")
if not isinstance(servers, dict) or not set(servers).issubset(known):
    raise SystemExit(2)
print(",".join(name for name in sorted(known) if name in servers))
'@ $installedMcpConfig 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[fail] installed MCP inventory is malformed or contains an unknown server. Rerun .\install.ps1." -ForegroundColor Red
        exit 3
    }
}

if (-not $mcpServers) {
    Write-Host "[ok] core harness is installed without automatic MCP servers. This may be an intentional core-only profile; rerun the installer with enabled servers if MCP is wanted."
} else {
    $needsNode = ($mcpServers -match "harness-context7") -or ($mcpServers -match "harness-playwright")
    if ($needsNode) {
        foreach ($runtime in @("node", "npx")) {
            if (-not (Get-Command $runtime -ErrorAction SilentlyContinue)) {
                Write-Host "[fail] enabled MCP runtime is missing: $runtime. Rerun .\install.ps1 after installing the development runtime." -ForegroundColor Red
                exit 3
            }
        }
        $nodeVersion = ((& node --version) 2>$null) -replace '^v', ''
        $nodeParts = $nodeVersion -split '\.'
        $nodeMajor = 0; $nodeMinor = 0; $nodePatch = 0
        [void][int]::TryParse(($nodeParts[0] -replace '[^0-9].*$', ''), [ref]$nodeMajor)
        [void][int]::TryParse(($nodeParts[1] -replace '[^0-9].*$', ''), [ref]$nodeMinor)
        [void][int]::TryParse(($nodeParts[2] -replace '[^0-9].*$', ''), [ref]$nodePatch)
        if ($nodeMajor -lt 20 -or ($nodeMajor -eq 20 -and $nodeMinor -lt 18) -or ($nodeMajor -eq 20 -and $nodeMinor -eq 18 -and $nodePatch -lt 1)) {
            Write-Host "[fail] enabled Node-based MCP requires Node.js 20.18.1 or newer; found $nodeVersion." -ForegroundColor Red
            exit 3
        }
    }

    if ($mcpServers -match "harness-serena" -and -not (Get-Command uvx -ErrorAction SilentlyContinue)) {
        Write-Host "[fail] enabled Serena MCP runtime is missing: uvx. Rerun .\install.ps1 after installing uv." -ForegroundColor Red
        exit 3
    }

    if ($mcpServers -match "harness-github") {
        $githubMcp = Join-Path (Split-Path -Parent $agyExecutable) "codex-harness-github-mcp-server"
        if (-not (Test-Path $githubMcp -PathType Leaf)) {
            $githubMcp = "$githubMcp.exe"
        }
        if (-not (Test-Path $githubMcp -PathType Leaf)) {
            Write-Host "[fail] checksum-verified GitHub MCP binary is missing. Rerun .\install.ps1." -ForegroundColor Red
            exit 3
        }
        $githubMcpVersion = & $githubMcp --version 2>&1 | Out-String
        if ($githubMcpVersion.Trim() -cne "Version: 1.10.1") {
            Write-Host "[fail] GitHub MCP version is not the pinned 1.10.1 release. Rerun .\install.ps1." -ForegroundColor Red
            exit 3
        }
    }
    Write-Host "[ok] automatic MCP inventory: $($mcpServers -join ', ')."

    if ($mcpServers -match "harness-playwright") {
        $playwrightInstallCommand = 'npx -y @playwright/mcp@0.0.79 install-browser chromium'
        $dryRunScript = @'
import os
import subprocess
import sys

environment = os.environ.copy()
environment["npm_config_fetch_retries"] = "1"
environment["npm_config_fetch_timeout"] = "5000"
try:
    result = subprocess.run(
        ["npx", "-y", "@playwright/mcp@0.0.79", "install-browser", "--dry-run", "chromium"],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
        timeout=20,
    )
except (OSError, subprocess.TimeoutExpired):
    raise SystemExit(1)
sys.stdout.write(result.stdout)
raise SystemExit(result.returncode)
'@
        $playwrightDryRun = $dryRunScript | & $pinnedPython - 2>$null
        if ($LASTEXITCODE -eq 0 -and $playwrightDryRun) {
            $playwrightLocations = ($playwrightDryRun | Out-String) -split "`r?`n" |
                Where-Object { $_ -match '^\s*Install location:\s*(.+)$' } |
                ForEach-Object { $Matches[1].Trim() }
            $playwrightMissing = $false
            foreach ($playwrightLocation in $playwrightLocations) {
                if (-not (Test-Path (Join-Path $playwrightLocation "INSTALLATION_COMPLETE") -PathType Leaf)) {
                    $playwrightMissing = $true
                    Write-Host "[warn] pinned Playwright browser component is missing or incomplete: $playwrightLocation"
                }
            }
            if (-not $playwrightLocations) {
                $readinessWarnings = 1
                Write-Host "[warn] Playwright MCP returned no browser install locations; unable to verify Chromium. Run: $playwrightInstallCommand"
            } elseif ($playwrightMissing) {
                $readinessWarnings = 1
                Write-Host "[warn] Install the browser revision pinned by the MCP package with: $playwrightInstallCommand"
            } else {
                Write-Host "[ok] Playwright Chromium and required components match @playwright/mcp@0.0.79."
            }
        } else {
            $readinessWarnings = 1
            Write-Host "[warn] unable to verify the Playwright browser revision within 20s (offline/proxy/npm unavailable). Run when online: $playwrightInstallCommand"
        }
    }
}

$policyTarget = Join-Path $HOME ".gemini/GEMINI.md"
if (-not (Test-Path $policyTarget -PathType Leaf) -or -not ((Get-Content $policyTarget -Raw).Contains("<!-- auto-harness:start -->"))) {
    Write-Host "[fail] always-on global policy is missing. Run .\install.ps1." -ForegroundColor Red
    exit 1
}
Write-Host "[ok] always-on global policy: $policyTarget"

$modelList = & $agyExecutable models | Out-String
if ($modelList -match "gemini-3.8-flash-high") {
    Write-Host "[ok] Gemini 3.8 Flash High is available."
    $preferredModel = "Gemini 3.8 Flash High"
} elseif ($modelList -match "gemini-3.7-flash-high") {
    Write-Host "[ok] Gemini 3.7 Flash High is available."
    $preferredModel = "Gemini 3.7 Flash High"
} else {
    Write-Host "[warn] Gemini 3.8 Flash High is not currently listed for this account."
    exit 2
}

if ($readinessWarnings -gt 0) {
    Write-Host "`nCore harness is ready; resolve the warnings above before relying on every automatic MCP. Use $preferredModel for maximum coding accuracy."
} else {
    Write-Host "`nEverything is ready. Run agy and select $preferredModel with /model for maximum coding accuracy."
}
