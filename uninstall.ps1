#Requires -Version 5.1
<#
.SYNOPSIS
    Removes what install.ps1 installed: the harness plugin, the managed
    GEMINI.md block (restoring the pre-install backup when present), and the
    pinned GitHub MCP binary. The installer never modifies settings.json, so
    terminal permissions and other user settings are left untouched.
#>
$ErrorActionPreference = "Stop"

$pluginName = "codex-claude-harness"
$policyDirectory = Join-Path $HOME ".gemini"
$policyTarget = Join-Path $policyDirectory "GEMINI.md"
$policyBackup = $policyTarget + ".bak"
$policyStartMarker = "<!-- auto-harness:start -->"
$policyEndMarker = "<!-- auto-harness:end -->"

$agyCommand = Get-Command agy -ErrorAction SilentlyContinue
$pluginRemoved = $false
if ($agyCommand) {
    & $agyCommand.Source plugin uninstall $pluginName 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $pluginRemoved = $true
        Write-Host "[ok] plugin uninstalled via agy."
    }
}
foreach ($candidateDir in @(
    (Join-Path $policyDirectory "config/plugins/$pluginName"),
    (Join-Path $policyDirectory "antigravity-cli/plugins/$pluginName"))) {
    if (Test-Path $candidateDir -PathType Container) {
        Remove-Item -Recurse -Force $candidateDir
        $pluginRemoved = $true
        Write-Host "[ok] removed $candidateDir"
    }
}
if (-not $pluginRemoved) {
    Write-Host "[skip] harness plugin was not installed."
}

if ($agyCommand) {
    $agyDirectory = Split-Path -Parent $agyCommand.Source
    foreach ($artifact in @(
        "codex-harness-github-mcp-server.exe",
        "codex-harness-github-mcp-server",
        "codex-harness-github-mcp-server.version")) {
        $artifactPath = Join-Path $agyDirectory $artifact
        if (Test-Path $artifactPath -PathType Leaf) {
            Remove-Item -Force $artifactPath
            Write-Host "[ok] removed $artifactPath"
        }
    }
}

if (Test-Path $policyBackup -PathType Leaf) {
    if (Test-Path $policyTarget -PathType Leaf) {
        [System.IO.File]::Replace($policyBackup, $policyTarget, $null)
    } else {
        [System.IO.File]::Move($policyBackup, $policyTarget)
    }
    Write-Host "[ok] restored $policyTarget from the pre-install backup."
}
elseif ((Test-Path $policyTarget -PathType Leaf) -and ((Get-Content $policyTarget -Raw).Contains($policyStartMarker))) {
    $existingPolicy = Get-Content $policyTarget -Raw
    $managedPattern = [regex]::Escape($policyStartMarker) + "[\s\S]*?" + [regex]::Escape($policyEndMarker) + "\r?\n?"
    $strippedPolicy = ([regex]::Replace($existingPolicy, $managedPattern, "")).TrimEnd()
    if ($strippedPolicy) {
        $policyTempPath = Join-Path $policyDirectory ("GEMINI.md.tmp-" + [Guid]::NewGuid().ToString("N"))
        try {
            [System.IO.File]::WriteAllText($policyTempPath, $strippedPolicy + [Environment]::NewLine, (New-Object System.Text.UTF8Encoding($false)))
            [System.IO.File]::Replace($policyTempPath, $policyTarget, $null)
        }
        finally {
            if (Test-Path $policyTempPath -PathType Leaf) {
                Remove-Item -Force $policyTempPath
            }
        }
        Write-Host "[ok] removed the managed block from $policyTarget"
    } else {
        Remove-Item -Force $policyTarget
        Write-Host "[ok] removed $policyTarget (it only contained the managed block)"
    }
}
else {
    Write-Host "[skip] no managed policy block found in $policyTarget."
}

Write-Host "Done. The installer never modifies settings.json, so no permission cleanup is needed."
