param(
  [ValidateSet("Lite", "Full")]
  [string]$Edition = "Lite",
  [string]$Python = "python",
  [string]$PyInstallerModule = "PyInstaller",
  [string]$ISCC = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
  [string]$NodeMajor = "22",
  [switch]$SkipRuntimeProvision,
  [switch]$ForceRuntimeProvision,
  [switch]$SkipInnoSetupAutoInstall
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$distDir = Join-Path $root "dist"
$releaseDir = Join-Path $root "Synpture"
$installerDir = $releaseDir
$specPath = Join-Path $root "packaging\synpture_launcher.spec"
$issPath = Join-Path $root "packaging\SynptureInstaller.iss"
$prepareRuntimeScript = Join-Path $root "scripts\prepare_windows_runtime.ps1"
$whisperBuildScript = Join-Path $root "tools\build_whisper_cpp.cmd"
$ffmpegDir = Join-Path $root "third_party\ffmpeg\bin"
$nodeDir = Join-Path $root "third_party\node"
$nodeRuntimeDir = Join-Path $root "third_party\node_runtime"
$chromiumDir = Join-Path $root "third_party\chromium"
$whisperCudaDir = Join-Path $root "third_party\whisper.cpp\build-cuda\bin"
$modelPath = Join-Path $root "models\ggml-large-v3-turbo-q5_0.bin"
$isFullEdition = $Edition -eq "Full"

function Assert-PathExists {
  param(
    [string]$PathToCheck,
    [string]$Message
  )

  if (-not (Test-Path $PathToCheck)) {
    throw $Message
  }
}

function Find-InnoSetupCompiler {
  $candidateRoots = @(
    "C:\Program Files (x86)",
    "C:\Program Files",
    (Join-Path $env:LOCALAPPDATA "Programs")
  ) | Where-Object { $_ -and (Test-Path $_) }

  foreach ($rootPath in $candidateRoots) {
    $match = Get-ChildItem -Path $rootPath -Recurse -Filter ISCC.exe -ErrorAction SilentlyContinue |
      Select-Object -First 1 -ExpandProperty FullName
    if ($match) {
      return $match
    }
  }
  return $null
}

function Ensure-InnoSetupCompiler {
  param(
    [string]$CompilerPath,
    [switch]$SkipAutoInstall
  )

  if (Test-Path $CompilerPath) {
    return $CompilerPath
  }
  $discoveredBeforeInstall = Find-InnoSetupCompiler
  if ($discoveredBeforeInstall) {
    return $discoveredBeforeInstall
  }
  if ($SkipAutoInstall) {
    throw "Inno Setup compiler not found: $CompilerPath"
  }

  $wingetPath = (Get-Command winget -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1)
  if (-not $wingetPath) {
    throw "Inno Setup compiler not found: $CompilerPath"
  }

  & $wingetPath install --id JRSoftware.InnoSetup -e --accept-package-agreements --accept-source-agreements --silent
  if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup compiler auto-install failed via winget."
  }

  $discoveredAfterInstall = Find-InnoSetupCompiler
  if ($discoveredAfterInstall) {
    return $discoveredAfterInstall
  }

  throw "Inno Setup compiler still not found after winget install: $CompilerPath"
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

function Get-WhisperRuntimeProblems {
  param([string]$BinDir)

  if (-not (Test-Path $BinDir)) {
    return @([pscustomobject]@{ Path = $BinDir; DebugDependencies = @("missing runtime directory") })
  }

  $files = Get-ChildItem -Path $BinDir -File | Where-Object { $_.Extension -in @(".exe", ".dll") }
  $problems = @()
  foreach ($file in $files) {
    $debugDependencies = Get-DebugRuntimeDependencies -BinaryPath $file.FullName
    if ($debugDependencies.Count -gt 0) {
      $problems += [pscustomobject]@{
        Path = $file.FullName
        DebugDependencies = $debugDependencies
      }
    }
  }
  return $problems
}

function Ensure-PortableWhisperCudaRuntime {
  param(
    [string]$BinDir,
    [string]$BuildScriptPath
  )

  $problems = Get-WhisperRuntimeProblems -BinDir $BinDir
  if ($problems.Count -eq 0 -and (Test-Path (Join-Path $BinDir "whisper-cli.exe"))) {
    return
  }

  Assert-PathExists $BuildScriptPath "Missing whisper.cpp build script: $BuildScriptPath"
  & cmd /c $BuildScriptPath
  if ($LASTEXITCODE -ne 0) {
    throw "Failed to rebuild whisper.cpp CUDA runtime in Release mode."
  }

  $problems = Get-WhisperRuntimeProblems -BinDir $BinDir
  if ($problems.Count -gt 0) {
    $problemSummary = ($problems | ForEach-Object {
      "{0}: {1}" -f $_.Path, ($_.DebugDependencies -join ", ")
    }) -join "; "
    throw "Bundled whisper.cpp CUDA runtime still depends on Debug CRT: $problemSummary"
  }
}

Push-Location $root
try {
  Assert-PathExists $specPath "Missing PyInstaller spec: $specPath"
  Assert-PathExists $issPath "Missing Inno Setup script: $issPath"
  if ($isFullEdition -or -not $SkipRuntimeProvision) {
    Assert-PathExists $prepareRuntimeScript "Missing runtime preparation script: $prepareRuntimeScript"
  }
  if ($isFullEdition) {
    Assert-PathExists $whisperBuildScript "Missing whisper.cpp build script: $whisperBuildScript"
    Assert-PathExists $modelPath "Missing bundled model file: $modelPath"
    Assert-PathExists $whisperCudaDir "Missing whisper.cpp CUDA runtime folder: $whisperCudaDir"
    Assert-PathExists (Join-Path $whisperCudaDir "whisper-cli.exe") "Missing whisper.cpp executable: $(Join-Path $whisperCudaDir 'whisper-cli.exe')"
  }

  & $Python -m pip install -r requirements.txt
  & $Python -m pip install pyinstaller

  if ($isFullEdition -and -not $SkipRuntimeProvision) {
    $prepareArgs = @(
      "-ExecutionPolicy", "Bypass",
      "-File", $prepareRuntimeScript,
      "-Python", $Python,
      "-NodeMajor", $NodeMajor
    )
    if ($ForceRuntimeProvision) {
      $prepareArgs += "-Force"
    }
    & powershell @prepareArgs
    if ($LASTEXITCODE -ne 0) {
      throw "Runtime preparation failed."
    }
  }

  if ($isFullEdition) {
    Ensure-PortableWhisperCudaRuntime -BinDir $whisperCudaDir -BuildScriptPath $whisperBuildScript
  }

  if (Test-Path $distDir) { Remove-Item $distDir -Recurse -Force }
  if (-not (Test-Path $installerDir)) { New-Item -ItemType Directory -Path $installerDir | Out-Null }
  Get-ChildItem -Path $installerDir -Filter "SynptureSetup-$Edition-x64.exe" -ErrorAction SilentlyContinue | Remove-Item -Force

  $env:SYNPTURE_INSTALLER_EDITION = $Edition

  & $Python -m $PyInstallerModule --noconfirm $specPath

  $bundleRoot = Join-Path $distDir "Synpture"
  if (-not (Test-Path $bundleRoot)) {
    throw "PyInstaller output not found: $bundleRoot"
  }

  if ($isFullEdition) {
    Assert-PathExists $ffmpegDir "Missing bundled ffmpeg runtime: $ffmpegDir"
    Assert-PathExists (Join-Path $ffmpegDir "ffmpeg.exe") "Missing ffmpeg.exe under: $ffmpegDir"
    Assert-PathExists (Join-Path $ffmpegDir "ffprobe.exe") "Missing ffprobe.exe under: $ffmpegDir"
    Assert-PathExists $nodeDir "Missing bundled Node runtime: $nodeDir"
    Assert-PathExists (Join-Path $nodeDir "node.exe") "Missing node.exe under: $nodeDir"
    Assert-PathExists $nodeRuntimeDir "Missing bundled Node package runtime: $nodeRuntimeDir"
    Assert-PathExists (Join-Path $nodeRuntimeDir "node_modules\playwright") "Missing Playwright package under: $(Join-Path $nodeRuntimeDir 'node_modules\\playwright')"
    Assert-PathExists $chromiumDir "Missing bundled Chromium runtime: $chromiumDir"
    Assert-PathExists (Join-Path $chromiumDir "chrome.exe") "Missing chrome.exe under: $chromiumDir"

    Copy-Item $ffmpegDir (Join-Path $bundleRoot "third_party\ffmpeg\bin") -Recurse -Force
    Copy-Item $nodeDir (Join-Path $bundleRoot "third_party\node") -Recurse -Force
    Copy-Item $nodeRuntimeDir (Join-Path $bundleRoot "third_party\node_runtime") -Recurse -Force
    Copy-Item $chromiumDir (Join-Path $bundleRoot "third_party\chromium") -Recurse -Force
  }

  $resolvedISCC = Ensure-InnoSetupCompiler -CompilerPath $ISCC -SkipAutoInstall:$SkipInnoSetupAutoInstall
  & $resolvedISCC "/DSetupBaseName=SynptureSetup-$Edition-x64" $issPath
}
finally {
  Remove-Item Env:\SYNPTURE_INSTALLER_EDITION -ErrorAction SilentlyContinue
  Pop-Location
}
