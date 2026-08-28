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

    $playwrightConfigurator = Join-Path $repoRoot "scripts/configure-playwright-mcp.js"
    $playwrightSourceConfig = Join-Path $repoRoot "plugin/codex-claude-harness/mcp_config.json"
    $playwrightFixtureConfig = Join-Path $testRoot "mcp_config.json"
    $defaultOrigins = "http://localhost:*;http://127.0.0.1:*;https://localhost:*;https://127.0.0.1:*"
    Copy-Item $playwrightSourceConfig $playwrightFixtureConfig -Force
    & node $playwrightConfigurator $playwrightFixtureConfig "unrestricted" $defaultOrigins
    if ($LASTEXITCODE -ne 0) {
        throw "Playwright configurator failed in unrestricted mode"
    }
    $playwrightArgs = @((Get-Content $playwrightFixtureConfig -Raw | ConvertFrom-Json).mcpServers."harness-playwright".args)
    if ($playwrightArgs -contains "--allowed-origins" -or $playwrightArgs -contains $defaultOrigins) {
        throw "unrestricted Playwright config retained its origin filter"
    }
    foreach ($requiredArgument in @("--isolated", "--headless")) {
        if ($playwrightArgs -notcontains $requiredArgument) {
            throw "unrestricted Playwright config lost $requiredArgument"
        }
    }

    Copy-Item $playwrightSourceConfig $playwrightFixtureConfig -Force
    & node $playwrightConfigurator $playwrightFixtureConfig "allowlist" $defaultOrigins
    if ($LASTEXITCODE -ne 0) {
        throw "Playwright configurator failed to restore loopback mode"
    }
    $playwrightArgs = @((Get-Content $playwrightFixtureConfig -Raw | ConvertFrom-Json).mcpServers."harness-playwright".args)
    if (($playwrightArgs | Where-Object { $_ -eq "--allowed-origins" }).Count -ne 1) {
        throw "restored Playwright config does not contain exactly one allowlist flag"
    }
    $allowlistIndex = -1
    for ($argumentIndex = 0; $argumentIndex -lt $playwrightArgs.Count; $argumentIndex++) {
        if ($playwrightArgs[$argumentIndex] -eq "--allowed-origins") {
            $allowlistIndex = $argumentIndex
            break
        }
    }
    if ($allowlistIndex -lt 0) {
        throw "restored Playwright config is missing its allowlist flag"
    }
    if ($playwrightArgs[$allowlistIndex + 1] -ne $defaultOrigins) {
        throw "restored Playwright config does not contain the exact loopback allowlist"
    }

    $originalAllowedOrigins = $env:HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS
    $originalErrorActionPreference = $ErrorActionPreference
    try {
        # Windows PowerShell 5.1 surfaces native stderr as NativeCommandError.
        # These two child processes are expected to fail, so capture their exit
        # codes and output without promoting that stderr to a terminating error.
        $ErrorActionPreference = "Continue"
        $env:HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS = "https://preview.example.com"
        & $currentPowerShell -NoProfile -File (Join-Path $repoRoot "install.ps1") -PlaywrightUnrestricted *> (Join-Path $testRoot "install-conflicting-origin.log")
        $conflictingOriginStatus = $LASTEXITCODE
        $env:HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS = $null
        & $currentPowerShell -NoProfile -File (Join-Path $repoRoot "install.ps1") -SkipMcp -PlaywrightUnrestricted *> (Join-Path $testRoot "install-conflicting-mode.log")
        $conflictingModeStatus = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $originalErrorActionPreference
        $env:HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS = $originalAllowedOrigins
    }
    if ($conflictingOriginStatus -eq 0 -or $conflictingModeStatus -eq 0) {
        throw "PowerShell installer accepted conflicting Playwright modes"
    }
    $conflictingOriginLog = Get-Content (Join-Path $testRoot "install-conflicting-origin.log") -Raw
    if (-not $conflictingOriginLog.Contains("cannot be combined") -or -not $conflictingOriginLog.Contains("HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS")) {
        throw "PowerShell installer did not explain the origin-mode conflict"
    }
    $conflictingModeLog = Get-Content (Join-Path $testRoot "install-conflicting-mode.log") -Raw
    if (-not $conflictingModeLog.Contains("cannot be combined") -or -not $conflictingModeLog.Contains("-PlaywrightUnrestricted")) {
        throw "PowerShell installer did not explain the skip-MCP conflict"
    }

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
