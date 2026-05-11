param(
  [string]$Python = "python",
  [string]$NodeMajor = "22",
  [switch]$Force
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$thirdPartyRoot = Join-Path $root "third_party"
$nodeDir = Join-Path $thirdPartyRoot "node"
$nodeModulesRoot = Join-Path $thirdPartyRoot "node_runtime"
$nodeModulesDir = Join-Path $nodeModulesRoot "node_modules"
$chromiumDir = Join-Path $thirdPartyRoot "chromium"
$ffmpegBinDir = Join-Path $thirdPartyRoot "ffmpeg\bin"
$whisperBuildScript = Join-Path $root "tools\build_whisper_cpp.cmd"
$whisperCudaBinDir = Join-Path $thirdPartyRoot "whisper.cpp\build-cuda\bin"
$runtimeManifestPath = Join-Path $thirdPartyRoot "runtime_manifest.json"
$packageJsonPath = Join-Path $root "package.json"
$packageLockPath = Join-Path $root "package-lock.json"

function New-TempDir {
  $path = Join-Path ([System.IO.Path]::GetTempPath()) ("synpture-runtime-" + [System.Guid]::NewGuid().ToString("N"))
  New-Item -ItemType Directory -Path $path -Force | Out-Null
  return $path
}

function Invoke-JsonRequest {
  param(
    [string]$Url,
    [hashtable]$Headers = @{}
  )

  return Invoke-RestMethod -Uri $Url -Headers $Headers
}

function Download-File {
  param(
    [string]$Url,
    [string]$Destination
  )

  Invoke-WebRequest -Uri $Url -OutFile $Destination
}

function Reset-Directory {
  param([string]$PathToReset)

  if (Test-Path $PathToReset) {
    Remove-Item $PathToReset -Recurse -Force
  }
  New-Item -ItemType Directory -Path $PathToReset -Force | Out-Null
}

function Get-DebugRuntimeDependencies {
  param([string]$BinaryPath)

  if (-not (Test-Path $BinaryPath)) {
    return @()
  }

  $payload = [System.Text.Encoding]::ASCII.GetString([System.IO.File]::ReadAllBytes($BinaryPath))
  $knownDebugDlls = @(
    "MSVCP140D.dll",
    "VCRUNTIME140D.dll",
    "VCRUNTIME140_1D.dll",
    "ucrtbased.dll"
  )

  return @($knownDebugDlls | Where-Object { $payload.Contains($_) })
}

function Test-PortableWhisperRuntime {
  param([string]$BinDir)

  $report = @()
  if (-not (Test-Path $BinDir)) {
    return [pscustomobject]@{
      IsPortable = $false
      CheckedFiles = @()
      Problems = @([pscustomobject]@{ Path = $BinDir; DebugDependencies = @("missing runtime directory") })
    }
  }

  $files = Get-ChildItem -Path $BinDir -File | Where-Object { $_.Extension -in @(".exe", ".dll") }
  foreach ($file in $files) {
    $debugDependencies = Get-DebugRuntimeDependencies -BinaryPath $file.FullName
    if ($debugDependencies.Count -gt 0) {
      $report += [pscustomobject]@{
        Path = $file.FullName
        DebugDependencies = $debugDependencies
      }
    }
  }

  return [pscustomobject]@{
    IsPortable = ($report.Count -eq 0)
    CheckedFiles = $files.FullName
    Problems = $report
  }
}

function Ensure-WhisperCudaRuntime {
  $initialStatus = Test-PortableWhisperRuntime -BinDir $whisperCudaBinDir
  if ($initialStatus.IsPortable -and (Test-Path (Join-Path $whisperCudaBinDir "whisper-cli.exe"))) {
    return [pscustomobject]@{
      Version = "existing"
      Rebuilt = $false
      BinDir = $whisperCudaBinDir
    }
  }

  if (-not (Test-Path $whisperBuildScript)) {
    throw "Missing whisper.cpp build script: $whisperBuildScript"
  }

  & cmd /c $whisperBuildScript
  if ($LASTEXITCODE -ne 0) {
    throw "Failed to rebuild whisper.cpp CUDA runtime in Release mode."
  }

  $finalStatus = Test-PortableWhisperRuntime -BinDir $whisperCudaBinDir
  if (-not $finalStatus.IsPortable) {
    $problemSummary = ($finalStatus.Problems | ForEach-Object {
      "{0}: {1}" -f $_.Path, ($_.DebugDependencies -join ", ")
    }) -join "; "
    throw "Bundled whisper.cpp CUDA runtime still depends on Debug CRT: $problemSummary"
  }

  return [pscustomobject]@{
    Version = "rebuilt-release"
    Rebuilt = $true
    BinDir = $whisperCudaBinDir
  }
}

function Get-PlaywrightVersion {
  if (Test-Path $packageLockPath) {
    $lockedVersion = @"
import json
from pathlib import Path
data = json.loads(Path(r'''$packageLockPath''').read_text(encoding='utf-8'))
print(data.get('packages', {}).get('node_modules/playwright', {}).get('version', ''))
"@ | & $Python -
    $lockedVersion = ($lockedVersion | Out-String).Trim()
    if ($lockedVersion) {
      return [string]$lockedVersion
    }
  }

  if (Test-Path $packageJsonPath) {
    $versionRange = @"
import json
from pathlib import Path
data = json.loads(Path(r'''$packageJsonPath''').read_text(encoding='utf-8'))
print(data.get('dependencies', {}).get('playwright', ''))
"@ | & $Python -
    $versionRange = ($versionRange | Out-String).Trim()
    if ($versionRange) {
      return ([string]$versionRange).TrimStart("^", "~")
    }
  }

  throw "Unable to resolve Playwright version from package.json/package-lock.json."
}

function Get-LatestNodeRelease {
  param([string]$PreferredMajor)

  $releases = Invoke-JsonRequest -Url "https://nodejs.org/dist/index.json"
  $ltsRelease = $releases |
    Where-Object { $_.lts -and $_.version -match "^v$PreferredMajor\." } |
    Select-Object -First 1

  if (-not $ltsRelease) {
    $ltsRelease = $releases | Where-Object { $_.lts } | Select-Object -First 1
  }
  if (-not $ltsRelease) {
    throw "Unable to locate an LTS Node.js release from nodejs.org/dist/index.json."
  }

  $version = [string]$ltsRelease.version
  return [pscustomobject]@{
    Version = $version
    Url = "https://nodejs.org/dist/$version/node-$version-win-x64.zip"
  }
}

function Install-NodeRuntime {
  param([string]$PreferredMajor)

  $existingNode = Join-Path $nodeDir "node.exe"
  if ((-not $Force) -and (Test-Path $existingNode)) {
    return [pscustomobject]@{
      Version = "existing"
      Url = $null
    }
  }

  $release = Get-LatestNodeRelease -PreferredMajor $PreferredMajor
  $tempDir = New-TempDir
  try {
    $zipPath = Join-Path $tempDir "node.zip"
    Download-File -Url $release.Url -Destination $zipPath
    Reset-Directory -PathToReset $nodeDir
    Expand-Archive -Path $zipPath -DestinationPath $tempDir -Force
    $expandedDir = Join-Path $tempDir ("node-" + $release.Version + "-win-x64")
    Copy-Item -Path (Join-Path $expandedDir "*") -Destination $nodeDir -Recurse -Force
  }
  finally {
    Remove-Item $tempDir -Recurse -Force -ErrorAction SilentlyContinue
  }

  return $release
}

function Install-PlaywrightPackage {
  param([string]$PlaywrightVersion)

  $npmCmd = Join-Path $nodeDir "npm.cmd"
  if (-not (Test-Path $npmCmd)) {
    throw "npm.cmd not found under bundled Node runtime: $npmCmd"
  }

  $installedVersion = $null
  $playwrightPackageJson = Join-Path $nodeModulesDir "playwright\package.json"
  if (Test-Path $playwrightPackageJson) {
    $installedVersion = (Get-Content -Path $playwrightPackageJson -Raw | ConvertFrom-Json).version
  }

  if ((-not $Force) -and $installedVersion -eq $PlaywrightVersion) {
    return
  }

  Reset-Directory -PathToReset $nodeModulesRoot
  & $npmCmd install --prefix $nodeModulesRoot "playwright@$PlaywrightVersion" --no-fund --no-audit
  if ($LASTEXITCODE -ne 0) {
    throw "Failed to install Playwright runtime package."
  }

  if (-not (Test-Path $playwrightPackageJson)) {
    throw "Playwright package was not installed into $nodeModulesDir"
  }
}

function Install-ChromiumRuntime {
  $existingChrome = Join-Path $chromiumDir "chrome.exe"
  if ((-not $Force) -and (Test-Path $existingChrome)) {
    return [pscustomobject]@{
      Version = "existing"
      SourcePath = $existingChrome
    }
  }

  $downloads = Invoke-JsonRequest -Url "https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json"
  $stable = $downloads.channels.Stable
  $asset = $stable.downloads.chrome | Where-Object { $_.platform -eq "win64" } | Select-Object -First 1
  if (-not $asset) {
    throw "Unable to locate a Windows x64 Chrome for Testing download."
  }

  $tempDir = New-TempDir
  try {
    $zipPath = Join-Path $tempDir "chrome-for-testing.zip"
    Download-File -Url $asset.url -Destination $zipPath
    Expand-Archive -Path $zipPath -DestinationPath $tempDir -Force
    $chromeExecutable = Get-ChildItem -Path $tempDir -Recurse -Filter "chrome.exe" | Select-Object -First 1
    if (-not $chromeExecutable) {
      throw "Downloaded Chrome for Testing archive does not contain chrome.exe."
    }

    Reset-Directory -PathToReset $chromiumDir
    Copy-Item -Path (Join-Path $chromeExecutable.Directory.FullName "*") -Destination $chromiumDir -Recurse -Force

    return [pscustomobject]@{
      Version = [string]$stable.version
      SourcePath = $chromeExecutable.FullName
      Url = [string]$asset.url
    }
  }
  finally {
    Remove-Item $tempDir -Recurse -Force -ErrorAction SilentlyContinue
  }
}

function Get-LatestFFmpegAsset {
  $release = Invoke-JsonRequest -Url "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/latest" -Headers @{ "User-Agent" = "SynptureBuild" }
  $preferredNames = @(
    "ffmpeg-master-latest-win64-gpl-shared.zip",
    "ffmpeg-master-latest-win64-lgpl-shared.zip"
  )

  $asset = $null
  foreach ($name in $preferredNames) {
    $asset = $release.assets | Where-Object { $_.name -eq $name } | Select-Object -First 1
    if ($asset) {
      break
    }
  }
  if (-not $asset) {
    $asset = $release.assets |
      Where-Object { $_.name -match "win64-.*shared.*\.zip$" } |
      Select-Object -First 1
  }
  if (-not $asset) {
    throw "Unable to locate a Windows x64 shared FFmpeg asset in the latest BtbN release."
  }

  return [pscustomobject]@{
    Tag = [string]$release.tag_name
    Name = [string]$asset.name
    Url = [string]$asset.browser_download_url
  }
}

function Install-FFmpegRuntime {
  $existingFfmpeg = Join-Path $ffmpegBinDir "ffmpeg.exe"
  $existingFfprobe = Join-Path $ffmpegBinDir "ffprobe.exe"
  if ((-not $Force) -and (Test-Path $existingFfmpeg) -and (Test-Path $existingFfprobe)) {
    return [pscustomobject]@{
      Version = "existing"
      AssetName = $null
      Url = $null
    }
  }

  $asset = Get-LatestFFmpegAsset
  $tempDir = New-TempDir
  try {
    $zipPath = Join-Path $tempDir "ffmpeg.zip"
    Download-File -Url $asset.Url -Destination $zipPath
    Expand-Archive -Path $zipPath -DestinationPath $tempDir -Force
    $binDir = Get-ChildItem -Path $tempDir -Recurse -Directory | Where-Object { $_.FullName -match "\\bin$" } | Select-Object -First 1
    if (-not $binDir) {
      throw "Extracted FFmpeg archive does not contain a bin directory."
    }

    Reset-Directory -PathToReset $ffmpegBinDir
    Copy-Item -Path (Join-Path $binDir.FullName "*") -Destination $ffmpegBinDir -Recurse -Force
  }
  finally {
    Remove-Item $tempDir -Recurse -Force -ErrorAction SilentlyContinue
  }

  return [pscustomobject]@{
    Version = $asset.Tag
    AssetName = $asset.Name
    Url = $asset.Url
  }
}

function Write-RuntimeManifest {
  param(
    [psobject]$NodeRelease,
    [string]$PlaywrightVersion,
    [psobject]$ChromiumRelease,
    [psobject]$FFmpegRelease,
    [psobject]$WhisperRelease
  )

  $manifest = [ordered]@{
    generatedAt = (Get-Date).ToString("s")
    node = $NodeRelease
    playwrightVersion = $PlaywrightVersion
    chromium = $ChromiumRelease
    ffmpeg = $FFmpegRelease
    whisperCuda = $WhisperRelease
  }

  $manifest | ConvertTo-Json -Depth 6 | Set-Content -Path $runtimeManifestPath -Encoding UTF8
}

Push-Location $root
try {
  $playwrightVersion = Get-PlaywrightVersion
  $nodeRelease = Install-NodeRuntime -PreferredMajor $NodeMajor
  Install-PlaywrightPackage -PlaywrightVersion $playwrightVersion
  $chromiumRelease = Install-ChromiumRuntime
  $ffmpegRelease = Install-FFmpegRuntime
  $whisperRelease = Ensure-WhisperCudaRuntime
  Write-RuntimeManifest -NodeRelease $nodeRelease -PlaywrightVersion $playwrightVersion -ChromiumRelease $chromiumRelease -FFmpegRelease $ffmpegRelease -WhisperRelease $whisperRelease
}
finally {
  Pop-Location
}
