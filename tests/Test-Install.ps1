$ErrorActionPreference = "Stop"
$onWindows = [Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT

$repoRoot = Split-Path -Parent $PSScriptRoot
$installerPath = Join-Path $repoRoot "install.ps1"
$exampleConfigPath = Join-Path $repoRoot "harness.config.example.json"
$testRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("auto-harness-test-" + [System.Guid]::NewGuid())
$fakeBin = Join-Path $testRoot "bin"
$runtimeBin = Join-Path $testRoot "runtime-only"
$fakeHome = Join-Path $testRoot "home"
$fakeTmp = Join-Path $testRoot "tmp"
$policyDirectory = Join-Path $fakeHome ".gemini"
$policyTarget = Join-Path $policyDirectory "GEMINI.md"
$agyCallLog = Join-Path $testRoot "agy-calls.log"
$currentPowerShell = (Get-Process -Id $PID).Path
$utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)

function Write-TestText([string] $Path, [string] $Contents) {
    [System.IO.File]::WriteAllText($Path, $Contents, $script:utf8WithoutBom)
}

function Write-TestConfig(
    [string] $Path,
    [string[]] $EnabledServers,
    [string] $PlaywrightMode = "loopback",
    [string[]] $AllowedOrigins = @()
) {
    $config = Get-Content $script:exampleConfigPath -Raw | ConvertFrom-Json
    foreach ($server in @("context7", "serena", "playwright", "github", "sentry")) {
        $config.mcp.servers.$server.enabled = $EnabledServers -contains $server
    }
    $config.mcp.servers.playwright.mode = $PlaywrightMode
    $config.mcp.servers.playwright.allowedOrigins = $AllowedOrigins
    Write-TestText $Path (($config | ConvertTo-Json -Depth 20) + [Environment]::NewLine)
}

function Invoke-TestInstaller(
    [string] $LogPath,
    [string] $CapturePath,
    [string[]] $Arguments = @(),
    [string] $ExpectedMcp = "1",
    [string] $PathOverride = ""
) {
    foreach ($path in @($LogPath, $CapturePath, $script:agyCallLog)) {
        if (Test-Path $path -PathType Leaf) {
            Remove-Item $path -Force
        }
    }
    $env:HARNESS_CAPTURE_MCP = $CapturePath
    $env:HARNESS_EXPECT_MCP_PRESENT = $ExpectedMcp
    if (-not [string]::IsNullOrEmpty($PathOverride)) {
        $env:PATH = $PathOverride
    }
    $processArguments = @("-NoProfile", "-File", $script:installerPath) + $Arguments
    $priorErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $script:currentPowerShell @processArguments *> $LogPath
        $status = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $priorErrorActionPreference
    }
    return $status
}

function Assert-OnlyServers([string] $ConfigPath, [string[]] $ExpectedServers) {
    if (-not (Test-Path $ConfigPath -PathType Leaf)) {
        throw "installer did not publish the expected MCP configuration: $ConfigPath"
    }
    $rendered = Get-Content $ConfigPath -Raw | ConvertFrom-Json
    $actual = @($rendered.mcpServers.PSObject.Properties | ForEach-Object { $_.Name })
    $expected = @($ExpectedServers | ForEach-Object { "harness-$_" })
    if (($actual -join ",") -ne ($expected -join ",")) {
        throw "unexpected MCP inventory: expected $($expected -join ','), found $($actual -join ',')"
    }
}

$originalHome = $env:HOME
$originalUserProfile = $env:USERPROFILE
$originalTmpDir = $env:TMPDIR
$originalPath = $env:PATH
$originalAllowedOrigins = $env:HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS
$originalSkipBootstrap = $env:HARNESS_SKIP_MCP_BOOTSTRAP
$originalCapture = $env:HARNESS_CAPTURE_MCP
$originalExpectedMcp = $env:HARNESS_EXPECT_MCP_PRESENT
$originalAgyCallLog = $env:HARNESS_AGY_CALL_LOG

try {
    New-Item -ItemType Directory -Force -Path $fakeBin, $runtimeBin, $policyDirectory, $fakeTmp | Out-Null
    Write-TestText $policyTarget "# Existing user rule`n`n- Keep this line.`n"

    if ($onWindows) {
        $fakeAgy = Join-Path $fakeBin "agy.cmd"
        Write-TestText $fakeAgy "@echo off`r`necho %*>>`"%HARNESS_AGY_CALL_LOG%`"`r`nif /i not `"%~1`"==`"plugin`" exit /b 20`r`nif `"%HARNESS_EXPECT_MCP_PRESENT%`"==`"1`" if not exist `"%~3\mcp_config.json`" exit /b 21`r`nif `"%HARNESS_EXPECT_MCP_PRESENT%`"==`"0`" if exist `"%~3\mcp_config.json`" exit /b 22`r`nif /i `"%~2`"==`"install`" if exist `"%~3\mcp_config.json`" copy /y `"%~3\mcp_config.json`" `"%HARNESS_CAPTURE_MCP%`" >nul`r`nexit /b 0`r`n"
    }
    else {
        $fakeAgy = Join-Path $fakeBin "agy"
        Write-TestText $fakeAgy @'
#!/bin/bash
printf '%s\n' "$*" >> "${HARNESS_AGY_CALL_LOG}"
[[ "${1:-}" == plugin ]] || exit 20
if [[ "${HARNESS_EXPECT_MCP_PRESENT:-}" == 1 && ! -f "${3:-}/mcp_config.json" ]]; then exit 21; fi
if [[ "${HARNESS_EXPECT_MCP_PRESENT:-}" == 0 && -f "${3:-}/mcp_config.json" ]]; then exit 22; fi
if [[ "${2:-}" == install && -f "${3:-}/mcp_config.json" ]]; then /bin/cp "${3}/mcp_config.json" "${HARNESS_CAPTURE_MCP}"; fi
exit 0
'@
        & chmod +x $fakeAgy
    }

    $nodeCommand = Get-Command node -ErrorAction Stop
    if ($onWindows) {
        $nodeShim = Join-Path $runtimeBin "node.cmd"
        Write-TestText $nodeShim "@echo off`r`nif `"%~1`"==`"--version`" echo v20.18.1& exit /b 0`r`n`"$($nodeCommand.Source)`" %*`r`n"
    }
    else {
        $nodeShim = Join-Path $runtimeBin "node"
        Write-TestText $nodeShim "#!/bin/bash`nif [[ `"`${1:-}`" == --version ]]; then printf 'v20.18.1\n'; exit 0; fi`nexec `"$($nodeCommand.Source)`" `"`$@`"`n"
        & chmod +x $nodeShim
    }
    $fullPath = "$fakeBin$([System.IO.Path]::PathSeparator)$runtimeBin$([System.IO.Path]::PathSeparator)$originalPath"
    $restrictedPath = "$fakeBin$([System.IO.Path]::PathSeparator)$runtimeBin"
    $env:HOME = $fakeHome
    $env:USERPROFILE = $fakeHome
    $env:TMPDIR = $fakeTmp
    $env:PATH = $fullPath
    $env:HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS = $null
    $env:HARNESS_SKIP_MCP_BOOTSTRAP = $null
    $env:HARNESS_AGY_CALL_LOG = $agyCallLog

    $installedPlugin = Join-Path $fakeHome ".gemini/config/plugins/codex-claude-harness"
    New-Item -ItemType Directory -Force -Path $installedPlugin | Out-Null
    Write-TestText (Join-Path $installedPlugin "mcp_config.json") '{"mcpServers":{"stale":{}}}'

    $invalidConfig = Join-Path $testRoot "invalid harness config.json"
    Write-TestText $invalidConfig '{"version":1,"mcp":{"servers":{"sentry":{"enabled":true}},"unexpected":true}}'
    $invalidLog = Join-Path $testRoot "invalid-config.log"
    $status = Invoke-TestInstaller $invalidLog (Join-Path $testRoot "invalid-output.json") @("-ConfigPath", $invalidConfig)
    if ($status -eq 0 -or (Test-Path $agyCallLog -PathType Leaf)) {
        throw "invalid configuration did not fail closed before invoking agy"
    }
    if (-not (Get-Content $invalidLog -Raw).Contains("MCP configuration validation failed")) {
        throw "installer did not report strict configuration validation failure"
    }

    $env:HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS = "https://preview.example.com"
    $conflictLog = Join-Path $testRoot "conflicting-playwright-overrides.log"
    $status = Invoke-TestInstaller $conflictLog (Join-Path $testRoot "conflicting-output.json") @("-PlaywrightUnrestricted")
    $env:HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS = $null
    if ($status -eq 0 -or -not (Get-Content $conflictLog -Raw).Contains("cannot be combined")) {
        throw "installer accepted conflicting legacy Playwright overrides"
    }
    $skipConflictLog = Join-Path $testRoot "skip-playwright-conflict.log"
    $status = Invoke-TestInstaller $skipConflictLog (Join-Path $testRoot "skip-conflict-output.json") @("-SkipMcp", "-PlaywrightUnrestricted") "0"
    if ($status -eq 0 -or -not (Get-Content $skipConflictLog -Raw).Contains("cannot be combined")) {
        throw "installer accepted -SkipMcp with a Playwright network override"
    }

    $spacedConfig = Join-Path $testRoot "profile with spaces.json"
    Write-TestConfig $spacedConfig @("sentry")
    $sentryCapture = Join-Path $testRoot "sentry-only.json"
    $sentryLog = Join-Path $testRoot "sentry-only.log"
    $status = Invoke-TestInstaller $sentryLog $sentryCapture @("-ConfigPath", $spacedConfig) "1" $restrictedPath
    if ($status -ne 0) { throw "installer failed a spaced ConfigPath with dependency-free Sentry enabled" }
    Assert-OnlyServers $sentryCapture @("sentry")
    $sentryOutput = Get-Content $sentryLog -Raw
    if ($sentryOutput.Contains("npx is unavailable") -or $sentryOutput.Contains("uvx is unavailable")) {
        throw "installer checked runtimes for disabled MCP servers"
    }

    $automaticPackage = Join-Path $testRoot "package with automatic profile"
    New-Item -ItemType Directory -Force -Path (Join-Path $automaticPackage "scripts"), (Join-Path $automaticPackage "global") | Out-Null
    Copy-Item -LiteralPath $installerPath -Destination (Join-Path $automaticPackage "install.ps1")
    Copy-Item -LiteralPath (Join-Path $repoRoot "scripts/render-mcp-config.js") -Destination (Join-Path $automaticPackage "scripts/render-mcp-config.js")
    Copy-Item -LiteralPath (Join-Path $repoRoot "global/GEMINI.md") -Destination (Join-Path $automaticPackage "global/GEMINI.md")
    Copy-Item -LiteralPath (Join-Path $repoRoot "plugin") -Destination (Join-Path $automaticPackage "plugin") -Recurse
    Write-TestConfig (Join-Path $automaticPackage "harness.config.json") @("sentry")
    $automaticCapture = Join-Path $testRoot "automatic-profile-output.json"
    $savedInstallerPath = $installerPath
    try {
        $script:installerPath = Join-Path $automaticPackage "install.ps1"
        $status = Invoke-TestInstaller (Join-Path $testRoot "automatic-profile.log") $automaticCapture @() "1" $restrictedPath
    }
    finally {
        $script:installerPath = $savedInstallerPath
    }
    if ($status -ne 0) { throw "installer failed to auto-discover its package-root harness.config.json" }
    Assert-OnlyServers $automaticCapture @("sentry")

    $partialConfig = Join-Path $testRoot "partial fallback.json"
    Write-TestConfig $partialConfig @("context7", "serena", "playwright", "sentry")
    $partialCapture = Join-Path $testRoot "partial-fallback-output.json"
    $partialLog = Join-Path $testRoot "partial-fallback.log"
    $status = Invoke-TestInstaller $partialLog $partialCapture @("-ConfigPath", $partialConfig) "1" $restrictedPath
    if ($status -ne 0) { throw "installer failed instead of retaining independent MCP servers" }
    Assert-OnlyServers $partialCapture @("sentry")
    $partialOutput = Get-Content $partialLog -Raw
    foreach ($expectedWarning in @("context7", "playwright", "serena", "uvx is unavailable")) {
        if (-not $partialOutput.Contains($expectedWarning)) { throw "partial fallback did not explain missing $expectedWarning" }
    }
    if (-not $partialOutput.Contains("npx is unavailable") -and -not $partialOutput.Contains("Node.js 20.18.1+ is required")) {
        throw "partial fallback did not explain why Node-based MCP servers were omitted"
    }

    $playwrightConfig = Join-Path $testRoot "playwright precedence.json"
    Write-TestConfig $playwrightConfig @("playwright", "sentry") "allowlist" @("https://from-config.example.com")
    $unrestrictedCapture = Join-Path $testRoot "playwright-unrestricted.json"
    $unrestrictedLog = Join-Path $testRoot "playwright-unrestricted.log"
    $status = Invoke-TestInstaller $unrestrictedLog $unrestrictedCapture @("-ConfigPath", $playwrightConfig, "-PlaywrightUnrestricted") "1" $fullPath
    if ($status -ne 0) { throw "legacy Playwright command-line override failed: $(Get-Content $unrestrictedLog -Raw)" }
    Assert-OnlyServers $unrestrictedCapture @("playwright", "sentry")
    $playwrightArgs = @((Get-Content $unrestrictedCapture -Raw | ConvertFrom-Json).mcpServers."harness-playwright".args)
    if ($playwrightArgs -contains "--allowed-origins" -or $playwrightArgs -contains "https://from-config.example.com") {
        throw "-PlaywrightUnrestricted did not override the profile"
    }

    $env:HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS = "https://preview.example.com"
    $extraCapture = Join-Path $testRoot "playwright-extra-origins.json"
    $status = Invoke-TestInstaller (Join-Path $testRoot "playwright-extra-origins.log") $extraCapture @("-ConfigPath", $playwrightConfig) "1" $fullPath
    $env:HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS = $null
    if ($status -ne 0) { throw "legacy Playwright environment override failed" }
    $playwrightArgs = @((Get-Content $extraCapture -Raw | ConvertFrom-Json).mcpServers."harness-playwright".args)
    $allowlistIndex = [array]::IndexOf($playwrightArgs, "--allowed-origins")
    $expectedOrigins = "http://localhost:*;http://127.0.0.1:*;https://localhost:*;https://127.0.0.1:*;https://preview.example.com"
    if ($allowlistIndex -lt 0 -or $playwrightArgs[$allowlistIndex + 1] -ne $expectedOrigins) {
        throw "HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS did not override the profile while retaining loopback"
    }

    foreach ($iteration in 1..2) {
        $status = Invoke-TestInstaller (Join-Path $testRoot "skip-$iteration.log") (Join-Path $testRoot "skip-output.json") @("-SkipMcp", "-ConfigPath", $invalidConfig) "0" $fullPath
        if ($status -ne 0) { throw "-SkipMcp did not override profile parsing on fixture run $iteration" }
    }
    $env:HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS = "not-an-origin"
    $status = Invoke-TestInstaller (Join-Path $testRoot "skip-origin-env.log") (Join-Path $testRoot "skip-origin-output.json") @("-SkipMcp", "-ConfigPath", $invalidConfig) "0" $fullPath
    $env:HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS = $null
    if ($status -ne 0) { throw "-SkipMcp did not ignore an unused Playwright origin environment value" }
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
    $env:HARNESS_SKIP_MCP_BOOTSTRAP = "1"
    $env:HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS = "not-an-origin"
    $status = Invoke-TestInstaller (Join-Path $testRoot "environment-skip.log") (Join-Path $testRoot "environment-skip-output.json") @("-ConfigPath", $invalidConfig) "0" $fullPath
    $env:HARNESS_SKIP_MCP_BOOTSTRAP = $null
    $env:HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS = $null
    if ($status -ne 0) { throw "HARNESS_SKIP_MCP_BOOTSTRAP did not preserve core-only precedence" }

    $validConfigWithoutNode = Join-Path $testRoot "valid but no node.json"
    Write-TestConfig $validConfigWithoutNode @("sentry")
    $missingNodeLog = Join-Path $testRoot "missing-node-config.log"
    $status = Invoke-TestInstaller $missingNodeLog (Join-Path $testRoot "missing-node-output.json") @("-ConfigPath", $validConfigWithoutNode) "1" $fakeBin
    if ($status -eq 0 -or (Test-Path $agyCallLog -PathType Leaf)) {
        throw "installer skipped an unvalidated profile or invoked agy when Node.js was missing"
    }

    $legacyCoreLog = Join-Path $testRoot "legacy-core-only.log"
    $status = Invoke-TestInstaller $legacyCoreLog (Join-Path $testRoot "legacy-core-only.json") @() "0" $fakeBin
    if ($status -ne 0 -or -not (Get-Content $legacyCoreLog -Raw).Contains("core-only")) {
        throw "missing Node.js did not preserve the reported legacy core-only fallback"
    }

    $policy = Get-Content $policyTarget -Raw
    if (-not $policy.Contains("- Keep this line.")) { throw "installer removed existing user policy" }
    if ([regex]::Matches($policy, [regex]::Escape("<!-- auto-harness:start -->")).Count -ne 1) { throw "installer duplicated the managed policy start marker" }
    if ([regex]::Matches($policy, [regex]::Escape("<!-- auto-harness:end -->")).Count -ne 1) { throw "installer duplicated the managed policy end marker" }
    if (-not $policy.Contains("# Automatic engineering harness")) { throw "installer did not add the managed policy" }

    Write-Host "[ok] PowerShell installer configuration and fallback checks passed"
}
finally {
    $env:HOME = $originalHome
    $env:USERPROFILE = $originalUserProfile
    $env:TMPDIR = $originalTmpDir
    $env:PATH = $originalPath
    $env:HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS = $originalAllowedOrigins
    $env:HARNESS_SKIP_MCP_BOOTSTRAP = $originalSkipBootstrap
    $env:HARNESS_CAPTURE_MCP = $originalCapture
    $env:HARNESS_EXPECT_MCP_PRESENT = $originalExpectedMcp
    $env:HARNESS_AGY_CALL_LOG = $originalAgyCallLog
    if (Test-Path $testRoot) {
        Remove-Item -Recurse -Force $testRoot
    }
}
