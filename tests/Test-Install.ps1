$ErrorActionPreference = "Stop"
$onWindows = [Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT

$repoRoot = Split-Path -Parent $PSScriptRoot
$testRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("auto-harness-test-" + [System.Guid]::NewGuid())
$fakeBin = Join-Path $testRoot "bin"
$fakeHome = Join-Path $testRoot "home"
$fakeTmp = Join-Path $testRoot "tmp"
$policyDirectory = Join-Path $fakeHome ".gemini"
$policyTarget = Join-Path $policyDirectory "GEMINI.md"
$currentPowerShell = (Get-Process -Id $PID).Path

try {
    New-Item -ItemType Directory -Force -Path $fakeBin, $policyDirectory, $fakeTmp | Out-Null
    [System.IO.File]::WriteAllText(
        $policyTarget,
        "# Existing user rule`n`n- Keep this line.`n",
        (New-Object System.Text.UTF8Encoding($false))
    )

    if ($onWindows) {
        $fakeAgy = Join-Path $fakeBin "agy.cmd"
        [System.IO.File]::WriteAllText(
            $fakeAgy,
            "@echo off`r`nif exist `"%~3\mcp_config.json`" exit /b 9`r`nexit /b 0`r`n",
            (New-Object System.Text.UTF8Encoding($false))
        )
    }
    else {
        $fakeAgy = Join-Path $fakeBin "agy"
        [System.IO.File]::WriteAllText(
            $fakeAgy,
            "#!/usr/bin/env bash`nset -euo pipefail`n[[ `${1:-} == plugin ]]`n[[ ! -f `"`${3:-}/mcp_config.json`" ]]`n",
            (New-Object System.Text.UTF8Encoding($false))
        )
        & chmod +x $fakeAgy
    }

    $installedPlugin = Join-Path $fakeHome ".gemini/config/plugins/codex-claude-harness"
    New-Item -ItemType Directory -Force -Path $installedPlugin | Out-Null
    [System.IO.File]::WriteAllText(
        (Join-Path $installedPlugin "mcp_config.json"),
        '{"mcpServers":{"stale":{}}}',
        (New-Object System.Text.UTF8Encoding($false))
    )

    $originalHome = $env:HOME
    $originalUserProfile = $env:USERPROFILE
    $originalTmpDir = $env:TMPDIR
    $originalPath = $env:PATH
    try {
        $env:HOME = $fakeHome
        $env:USERPROFILE = $fakeHome
        $env:TMPDIR = $fakeTmp
        $env:PATH = "$fakeBin$([System.IO.Path]::PathSeparator)$originalPath"
        foreach ($iteration in 1..2) {
            & $currentPowerShell -NoProfile -File (Join-Path $repoRoot "install.ps1") -SkipMcp *> (Join-Path $testRoot "install-$iteration.log")
            if ($LASTEXITCODE -ne 0) {
                throw "install.ps1 fixture run $iteration failed"
            }
        }
    }
    finally {
        $env:HOME = $originalHome
        $env:USERPROFILE = $originalUserProfile
        $env:TMPDIR = $originalTmpDir
        $env:PATH = $originalPath
    }

    $policy = Get-Content $policyTarget -Raw
    if (-not $policy.Contains("- Keep this line.")) {
        throw "installer removed existing user policy"
    }
    if ([regex]::Matches($policy, [regex]::Escape("<!-- auto-harness:start -->")).Count -ne 1) {
        throw "installer duplicated the managed policy start marker"
    }
    if ([regex]::Matches($policy, [regex]::Escape("<!-- auto-harness:end -->")).Count -ne 1) {
        throw "installer duplicated the managed policy end marker"
    }
    if (-not $policy.Contains("# Automatic engineering harness")) {
        throw "installer did not add the managed policy"
    }
    if (Test-Path (Join-Path $installedPlugin "mcp_config.json") -PathType Leaf) {
        throw "core-only installer left a stale enabled MCP config in the installed plugin"
    }
    $runtimeMarker = Join-Path $installedPlugin "scripts/.python-runtime"
    if (-not (Test-Path $runtimeMarker -PathType Leaf)) {
        throw "installer did not persist the pinned hook runtime marker"
    }
    $strictUtf8 = New-Object System.Text.UTF8Encoding($false, $true)
    $installedPython = [System.IO.File]::ReadAllText($runtimeMarker, $strictUtf8).Trim()
    if (-not [System.IO.Path]::IsPathRooted($installedPython) -or -not (Test-Path $installedPython -PathType Leaf)) {
        throw "installer persisted an invalid pinned hook runtime"
    }
    if ((Get-Content $runtimeMarker).Count -ne 1) {
        throw "installer runtime marker is not idempotent"
    }

    Write-Host "[ok] PowerShell installer fixture checks passed"
}
finally {
    if (Test-Path $testRoot) {
        Remove-Item -Recurse -Force $testRoot
    }
}
