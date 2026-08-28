param(
    [Alias("skip-mcp")]
    [switch]$SkipMcp
)

$ErrorActionPreference = "Stop"
$onWindows = [Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT

$packageRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pluginDir = Join-Path $packageRoot "plugin/codex-claude-harness"
$manifestPath = Join-Path $pluginDir "plugin.json"
$policySource = Join-Path $packageRoot "global/GEMINI.md"
$githubMcpVersion = "1.10.1"
$githubMcpStatus = "skipped"
$mcpEnabled = $true
$playwrightDefaultOrigins = "http://localhost:*;http://127.0.0.1:*;https://localhost:*;https://127.0.0.1:*"
$playwrightExtraOrigins = $env:HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS
$pluginInstallSource = $pluginDir
$pluginTemporaryDirectory = $null
$pythonRuntime = $null

if ($env:HARNESS_SKIP_MCP_BOOTSTRAP -eq "1") {
    $SkipMcp = $true
}

if (-not (Test-Path $manifestPath -PathType Leaf)) {
    throw "Plugin source not found at $pluginDir"
}

if (-not (Test-Path $policySource -PathType Leaf)) {
    throw "Global harness policy not found at $policySource"
}

$agyCommand = Get-Command agy -ErrorAction SilentlyContinue
$agyWasInstalled = $null -ne $agyCommand
if (-not $agyCommand) {
    Write-Host "Antigravity CLI is not installed; running the official installer..."
    $installer = Invoke-RestMethod "https://antigravity.google/cli/install.ps1"
    & ([scriptblock]::Create($installer))

    $agyBin = Join-Path $env:LOCALAPPDATA "agy/bin"
    $env:PATH = "$agyBin;$env:PATH"
    $agyCommand = Get-Command agy -ErrorAction SilentlyContinue
}

if (-not $agyCommand) {
    throw "agy was installed but is not available on PATH. Open a new terminal and rerun this installer."
}

$agyExecutable = $agyCommand.Source

function Test-HarnessTrustedPythonRuntime([string] $Path) {
    if (-not [System.IO.Path]::IsPathRooted($Path) -or -not (Test-Path $Path -PathType Leaf)) {
        return $false
    }
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $separator = [System.IO.Path]::DirectorySeparatorChar
    foreach ($root in @($packageRoot, [System.IO.Path]::GetTempPath())) {
        $fullRoot = [System.IO.Path]::GetFullPath($root).TrimEnd($separator)
        if (
            $fullPath.Equals($fullRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
            $fullPath.StartsWith("$fullRoot$separator", [System.StringComparison]::OrdinalIgnoreCase)
        ) {
            return $false
        }
    }
    return $true
}

foreach ($pythonName in @("python3", "python", "py")) {
    $pythonCommand = Get-Command $pythonName -ErrorAction SilentlyContinue
    if (-not $pythonCommand) { continue }
    $launcherArguments = if ($pythonName -eq "py") { @("-3") } else { @() }
    try {
        $resolvedPython = (& $pythonCommand.Source @launcherArguments -c "import os, sys; sys.exit(1) if sys.version_info < (3, 8) else print(os.path.realpath(sys.executable))" 2>$null | Out-String).Trim()
        if (($LASTEXITCODE -eq 0) -and (Test-HarnessTrustedPythonRuntime $resolvedPython)) {
            $pythonRuntime = [System.IO.Path]::GetFullPath($resolvedPython)
            break
        }
    }
    catch {
        continue
    }
}
if (-not $pythonRuntime) {
    Write-Warning "Python 3.8+ was not found; lifecycle security will require review and verification will fail open."
}

function Install-HarnessGitHubMcp {
    foreach ($runtime in @("node", "npx", "uvx")) {
        if (-not (Get-Command $runtime -ErrorAction SilentlyContinue)) {
            throw "Automatic MCP setup requires $runtime. Install Node.js 20.18.1+ (with npx) and uv (with uvx), then rerun install.ps1."
        }
    }
    $nodeVersionText = (& node --version).Trim().TrimStart("v")
    $nodeVersion = $null
    if (-not [System.Version]::TryParse($nodeVersionText, [ref]$nodeVersion) -or $nodeVersion -lt [System.Version]"20.18.1") {
        throw "Context7 requires Node.js 20.18.1 or newer; found $nodeVersionText."
    }

    $architecture = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
    switch ($architecture) {
        "Arm64" {
            $archiveName = "github-mcp-server_Windows_arm64.zip"
            $expectedHash = "7bc50942376f254192f0e28b3f76975a862f04e58bc7fa3a5b0d698d7a2d5d16"
        }
        "X64" {
            $archiveName = "github-mcp-server_Windows_x86_64.zip"
            $expectedHash = "3b94ca079cf51a54698401b7affea7288a64b38118c243ae488dd8dd96f4ffb2"
        }
        "X86" {
            $archiveName = "github-mcp-server_Windows_i386.zip"
            $expectedHash = "ae2c9191629122e33c503b53b8c3cc0b7bf56596d876e1f23476bd03f7039dd7"
        }
        default {
            throw "GitHub MCP bootstrap does not support Windows architecture $architecture"
        }
    }

    $agyBinDirectory = Split-Path -Parent $agyExecutable
    $target = Join-Path $agyBinDirectory "codex-harness-github-mcp-server.exe"
    $marker = "$target.version"
    if ((Test-Path $target -PathType Leaf) -and (Test-Path $marker -PathType Leaf)) {
        $installedVersion = (Get-Content $marker -Raw).Trim()
        if ($installedVersion -eq $githubMcpVersion) {
            try {
                $installedVersionOutput = (& $target --version 2>&1 | Out-String)
                $installedVersionExitCode = $LASTEXITCODE
            }
            catch {
                $installedVersionOutput = ""
                $installedVersionExitCode = 1
            }
            $expectedVersionPattern = "(?m)^$([regex]::Escape("Version: $githubMcpVersion"))\r?$"
            if (($installedVersionExitCode -eq 0) -and ($installedVersionOutput -match $expectedVersionPattern)) {
                $script:githubMcpStatus = "v$githubMcpVersion already installed and verified"
                return
            }
            Write-Host "Existing GitHub MCP failed version verification; reinstalling v$githubMcpVersion..."
        }
    }

    Write-Host "Downloading pinned GitHub MCP server v$githubMcpVersion..."
    $temporaryDirectory = Join-Path ([System.IO.Path]::GetTempPath()) ("github-mcp-" + [System.Guid]::NewGuid())
    New-Item -ItemType Directory -Path $temporaryDirectory | Out-Null
    try {
        $archivePath = Join-Path $temporaryDirectory $archiveName
        $downloadUrl = "https://github.com/github/github-mcp-server/releases/download/v$githubMcpVersion/$archiveName"
        Invoke-WebRequest -Uri $downloadUrl -OutFile $archivePath
        $actualHash = (Get-FileHash -Algorithm SHA256 $archivePath).Hash.ToLowerInvariant()
        if ($actualHash -ne $expectedHash) {
            throw "GitHub MCP checksum mismatch for $archiveName"
        }

        $extractDirectory = Join-Path $temporaryDirectory "extracted"
        Expand-Archive -Path $archivePath -DestinationPath $extractDirectory
        $executable = Get-ChildItem $extractDirectory -Recurse -File -Filter "github-mcp-server.exe" | Select-Object -First 1
        if (-not $executable) {
            throw "GitHub MCP archive did not contain the expected executable"
        }
        Copy-Item $executable.FullName $target -Force
        [System.IO.File]::WriteAllText($marker, "$githubMcpVersion`r`n", [System.Text.Encoding]::ASCII)
        $script:githubMcpStatus = "v$githubMcpVersion installed and verified"
    }
    finally {
        if (Test-Path $temporaryDirectory -PathType Container) {
            Remove-Item -Recurse -Force $temporaryDirectory
        }
    }
}

function Test-HarnessPlaywrightOriginList([string] $Origins) {
    if ([string]::IsNullOrEmpty($Origins)) {
        return
    }

    foreach ($origin in $Origins.Split(";")) {
        $uri = $null
        $validUri = [System.Uri]::TryCreate($origin, [System.UriKind]::Absolute, [ref]$uri)
        if (
            [string]::IsNullOrEmpty($origin) -or
            $origin.Contains("*") -or
            -not $validUri -or
            $uri.Scheme -notin @("http", "https") -or
            -not [string]::IsNullOrEmpty($uri.UserInfo) -or
            $uri.AbsolutePath -ne "/" -or
            -not [string]::IsNullOrEmpty($uri.Query) -or
            -not [string]::IsNullOrEmpty($uri.Fragment)
        ) {
            throw "HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS must be a semicolon-separated list of exact HTTP(S) origins without paths, credentials, or wildcards; invalid value: $origin"
        }
    }
}

function Resolve-HarnessPluginInstallSource {
    $script:pluginTemporaryDirectory = Join-Path ([System.IO.Path]::GetTempPath()) ("codex-harness-plugin-" + [System.Guid]::NewGuid())
    New-Item -ItemType Directory -Path $script:pluginTemporaryDirectory | Out-Null
    Copy-Item (Join-Path $script:pluginDir "*") $script:pluginTemporaryDirectory -Recurse -Force
    $script:pluginInstallSource = $script:pluginTemporaryDirectory

    $runtimeMarker = Join-Path $script:pluginInstallSource "scripts/.python-runtime"
    if ($script:pythonRuntime) {
        [System.IO.File]::WriteAllText($runtimeMarker, "$script:pythonRuntime$([Environment]::NewLine)", (New-Object System.Text.UTF8Encoding($false)))
        if (-not $script:onWindows) { & chmod 600 $runtimeMarker }
    }
    elseif (Test-Path $runtimeMarker -PathType Leaf) {
        Remove-Item $runtimeMarker -Force
    }

    $mcpConfigPath = Join-Path $script:pluginInstallSource "mcp_config.json"
    if (-not $script:mcpEnabled) {
        Remove-Item $mcpConfigPath -Force
        return
    }

    $config = Get-Content $mcpConfigPath -Raw | ConvertFrom-Json
    $arguments = [System.Collections.ArrayList]@($config.mcpServers."harness-playwright".args)
    $allowlistIndex = $arguments.IndexOf("--allowed-origins")
    if ($allowlistIndex -lt 0 -or $allowlistIndex + 1 -ge $arguments.Count) {
        throw "Playwright allowlist argument is missing from mcp_config.json"
    }
    $arguments[$allowlistIndex + 1] = "$script:playwrightDefaultOrigins;$script:playwrightExtraOrigins"
    $config.mcpServers."harness-playwright".args = $arguments.ToArray()
    $json = $config | ConvertTo-Json -Depth 20
    [System.IO.File]::WriteAllText($mcpConfigPath, "$json$([Environment]::NewLine)", (New-Object System.Text.UTF8Encoding($false)))
}

if ($SkipMcp) {
    $mcpEnabled = $false
    $githubMcpStatus = "skipped; core-only plugin requested"
}
else {
    Test-HarnessPlaywrightOriginList $playwrightExtraOrigins
    try {
        Install-HarnessGitHubMcp
    }
    catch {
        $mcpEnabled = $false
        $githubMcpStatus = "unavailable; installed core-only harness"
        Write-Warning "MCP bootstrap unavailable: $($_.Exception.Message). Continuing with the core harness only."
        Write-Warning "Fix the runtime/network issue and rerun install.ps1 to enable MCP."
    }
}

try {
    Resolve-HarnessPluginInstallSource

    Write-Host "Validating harness plugin..."
    & $agyExecutable plugin validate $pluginInstallSource
    if ($LASTEXITCODE -ne 0) {
        throw "Plugin validation failed."
    }

    Write-Host "Installing or updating harness plugin..."
    & $agyExecutable plugin install $pluginInstallSource
    if ($LASTEXITCODE -ne 0) {
        throw "Plugin installation failed."
    }
}
finally {
    if ($pluginTemporaryDirectory -and (Test-Path $pluginTemporaryDirectory -PathType Container)) {
        Remove-Item -Recurse -Force $pluginTemporaryDirectory
    }
}

Write-Host "Installing or updating always-on global policy..."
$policyDirectory = Join-Path $HOME ".gemini"
$policyTarget = Join-Path $policyDirectory "GEMINI.md"
$policyStartMarker = "<!-- auto-harness:start -->"
$policyEndMarker = "<!-- auto-harness:end -->"
New-Item -ItemType Directory -Force -Path $policyDirectory | Out-Null

$existingPolicy = ""
if (Test-Path $policyTarget -PathType Leaf) {
    $existingPolicy = Get-Content $policyTarget -Raw
}
$managedPattern = [regex]::Escape($policyStartMarker) + "[\s\S]*?" + [regex]::Escape($policyEndMarker) + "\r?\n?"
$preservedPolicy = ([regex]::Replace($existingPolicy, $managedPattern, "")).TrimEnd()
$managedPolicy = $policyStartMarker + [Environment]::NewLine + (Get-Content $policySource -Raw).TrimEnd() + [Environment]::NewLine + $policyEndMarker
if ($preservedPolicy) {
    $mergedPolicy = $preservedPolicy + [Environment]::NewLine + [Environment]::NewLine + $managedPolicy + [Environment]::NewLine
} else {
    $mergedPolicy = $managedPolicy + [Environment]::NewLine
}
$utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($policyTarget, $mergedPolicy, $utf8WithoutBom)

function Format-ByteSize([long] $Bytes) {
    if ($Bytes -ge 1GB) { return "{0:N2} GB" -f ($Bytes / 1GB) }
    if ($Bytes -ge 1MB) { return "{0:N2} MB" -f ($Bytes / 1MB) }
    if ($Bytes -ge 1KB) { return "{0:N2} KB" -f ($Bytes / 1KB) }
    return "$Bytes bytes"
}

$cliBytes = (Get-Item $agyExecutable).Length
$cliSize = Format-ByteSize $cliBytes
$pluginInstallDir = $null
$pluginCandidates = @(
    (Join-Path $HOME ".gemini/config/plugins/codex-claude-harness"),
    (Join-Path $HOME ".gemini/antigravity-cli/plugins/codex-claude-harness")
)
foreach ($candidateDir in $pluginCandidates) {
    if (Test-Path $candidateDir -PathType Container) {
        $pluginInstallDir = $candidateDir
        break
    }
}

if ($pluginInstallDir) {
    $installedRuntimeMarker = Join-Path $pluginInstallDir "scripts/.python-runtime"
    if ($pythonRuntime) {
        New-Item -ItemType Directory -Force -Path (Join-Path $pluginInstallDir "scripts") | Out-Null
        [System.IO.File]::WriteAllText($installedRuntimeMarker, "$pythonRuntime$([Environment]::NewLine)", (New-Object System.Text.UTF8Encoding($false)))
        if ($onWindows) {
            $acl = Get-Acl $installedRuntimeMarker
            $acl.SetAccessRuleProtection($true, $false)
            $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
            $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
                $identity,
                [System.Security.AccessControl.FileSystemRights]::FullControl,
                [System.Security.AccessControl.AccessControlType]::Allow
            )
            $acl.SetAccessRule($rule)
            Set-Acl $installedRuntimeMarker $acl
        }
        else {
            & chmod 600 $installedRuntimeMarker
        }
    }
    elseif (Test-Path $installedRuntimeMarker -PathType Leaf) {
        Remove-Item $installedRuntimeMarker -Force
    }
}

if (-not $mcpEnabled -and $pluginInstallDir) {
    $installedMcpConfig = Join-Path $pluginInstallDir "mcp_config.json"
    if (Test-Path $installedMcpConfig -PathType Leaf) {
        Remove-Item $installedMcpConfig -Force
    }
}

$pluginSize = "không xác định"
$pluginBytes = 0
if ($pluginInstallDir) {
    $pluginBytes = (Get-ChildItem $pluginInstallDir -Recurse -File | Measure-Object -Property Length -Sum).Sum
    $pluginSize = Format-ByteSize $pluginBytes
}
$totalSize = Format-ByteSize ($cliBytes + $pluginBytes)

$agyStatus = "đã có sẵn, giữ nguyên"
if (-not $agyWasInstalled) {
    $agyStatus = "vừa cài mới"
}

$skillCount = @(Get-ChildItem (Join-Path $pluginDir "skills") -Recurse -Filter "SKILL.md" -File).Count
$agentCount = @(Get-ChildItem (Join-Path $pluginDir "agents") -Filter "*.md" -File).Count
$componentSummary = "$skillCount skills, $agentCount subagents, 1 policy rule"
if (Test-Path (Join-Path $pluginDir "hooks.json") -PathType Leaf) {
    $componentSummary += ", 4 lifecycle hooks"
}
if ($mcpEnabled) {
    $componentSummary += ", 5 auto-routed MCP servers"
}
else {
    $componentSummary += ", core-only (MCP disabled)"
}

Write-Host ""
Write-Host "============================================================"
Write-Host "CÀI ĐẶT THÀNH CÔNG"
Write-Host "============================================================"
Write-Host "Antigravity CLI  : $agyExecutable"
Write-Host "Trạng thái       : $agyStatus"
Write-Host "Dung lượng CLI   : $cliSize"
if ($pluginInstallDir) {
    Write-Host "Harness plugin   : $pluginInstallDir"
} else {
    Write-Host "Harness plugin   : đã cài, nhưng CLI không công bố đường dẫn staging"
}
Write-Host "Dung lượng plugin: $pluginSize"
Write-Host "Global policy    : $policyTarget"
Write-Host "GitHub MCP       : $githubMcpStatus"
Write-Host "Tổng dung lượng  : $totalSize"
Write-Host "Thành phần       : $componentSummary"
Write-Host "Nguồn cài        : $packageRoot"
Write-Host "============================================================"
Write-Host "Dùng hằng ngày   : cd C:\duong\dan\project; agy"
Write-Host "Model coding     : chọn Gemini 3.7 Flash High bằng /model (được lưu qua các phiên)"
Write-Host "Lần chạy đầu có thể mở browser để đăng nhập Google."
