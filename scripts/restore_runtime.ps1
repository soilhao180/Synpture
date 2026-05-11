param(
  [string]$Python = "python",
  [string]$NodeMajor = "22",
  [string]$ModelUrl = "",
  [string]$WhisperCppRepo = "https://github.com/ggml-org/whisper.cpp.git",
  [string]$WhisperCppRef = "fc674574ca27cac59a15e5b22a09b9d9ad62aafe",
  [switch]$Force,
  [switch]$SkipRuntimeProvision,
  [switch]$SkipWhisperSource,
  [switch]$SkipModel
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$prepareRuntimeScript = Join-Path $root "scripts\prepare_windows_runtime.ps1"
$thirdPartyRoot = Join-Path $root "third_party"
$whisperSourceDir = Join-Path $thirdPartyRoot "whisper.cpp"
$modelDir = Join-Path $root "models"
$modelPath = Join-Path $modelDir "ggml-large-v3-turbo-q5_0.bin"

function Write-Step {
  param([string]$Message)
  Write-Host ""
  Write-Host "==> $Message" -ForegroundColor Cyan
}

function Assert-PathExists {
  param(
    [string]$PathToCheck,
    [string]$Message
  )
  if (-not (Test-Path -LiteralPath $PathToCheck)) {
    throw $Message
  }
}

function Download-File {
  param(
    [string]$Url,
    [string]$Destination
  )
  $parent = Split-Path -Parent $Destination
  New-Item -ItemType Directory -Path $parent -Force | Out-Null
  $tempPath = "$Destination.download"
  if (Test-Path -LiteralPath $tempPath) {
    Remove-Item -LiteralPath $tempPath -Force
  }
  Invoke-WebRequest -Uri $Url -OutFile $tempPath
  Move-Item -LiteralPath $tempPath -Destination $Destination -Force
}

function Restore-WhisperSource {
  if ($SkipWhisperSource) {
    Write-Step "Skipping whisper.cpp source restore"
    return
  }

  $cmakePath = Join-Path $whisperSourceDir "CMakeLists.txt"
  if ((-not $Force) -and (Test-Path -LiteralPath $cmakePath)) {
    Write-Step "whisper.cpp source already exists"
    Write-Host $whisperSourceDir
    return
  }

  $gitCommand = Get-Command git -ErrorAction SilentlyContinue
  if (-not $gitCommand) {
    throw "git is required to restore whisper.cpp source. Install Git for Windows or place whisper.cpp under third_party\whisper.cpp."
  }

  Write-Step "Restoring whisper.cpp source"
  New-Item -ItemType Directory -Path $thirdPartyRoot -Force | Out-Null
  if (Test-Path -LiteralPath $whisperSourceDir) {
    Remove-Item -LiteralPath $whisperSourceDir -Recurse -Force
  }

  & git clone --filter=blob:none $WhisperCppRepo $whisperSourceDir
  if ($LASTEXITCODE -ne 0) {
    throw "Failed to clone whisper.cpp from $WhisperCppRepo."
  }

  Push-Location $whisperSourceDir
  try {
    & git checkout $WhisperCppRef
    if ($LASTEXITCODE -ne 0) {
      throw "Failed to checkout whisper.cpp ref $WhisperCppRef."
    }
  }
  finally {
    Pop-Location
  }
}

Push-Location $root
try {
  Restore-WhisperSource

  if (-not $SkipRuntimeProvision) {
    Assert-PathExists $prepareRuntimeScript "Missing runtime provision script: $prepareRuntimeScript"
    Write-Step "Restoring bundled runtime dependencies"
    $runtimeArgs = @(
      "-ExecutionPolicy", "Bypass",
      "-File", $prepareRuntimeScript,
      "-Python", $Python,
      "-NodeMajor", $NodeMajor
    )
    if ($Force) {
      $runtimeArgs += "-Force"
    }
    & powershell @runtimeArgs
    if ($LASTEXITCODE -ne 0) {
      throw "Runtime provisioning failed."
    }
  }
  else {
    Write-Step "Skipping runtime provisioning"
  }

  if (-not $SkipModel) {
    if (Test-Path -LiteralPath $modelPath) {
      $sizeMb = [Math]::Round(((Get-Item -LiteralPath $modelPath).Length / 1MB), 1)
      Write-Step "Transcription model already exists ($sizeMb MB)"
      Write-Host $modelPath
    }
    elseif ($ModelUrl.Trim()) {
      Write-Step "Downloading transcription model"
      Download-File -Url $ModelUrl.Trim() -Destination $modelPath
      $sizeMb = [Math]::Round(((Get-Item -LiteralPath $modelPath).Length / 1MB), 1)
      Write-Host "Downloaded model to $modelPath ($sizeMb MB)"
    }
    else {
      Write-Step "Transcription model is missing"
      Write-Host "Expected model path:" -ForegroundColor Yellow
      Write-Host "  $modelPath"
      Write-Host ""
      Write-Host "Place ggml-large-v3-turbo-q5_0.bin there, or run again with:" -ForegroundColor Yellow
      Write-Host "  powershell -ExecutionPolicy Bypass -File scripts/restore_runtime.ps1 -ModelUrl <download-url>"
      Write-Host ""
      Write-Host "The app can still start, but local media/share-link transcription will stop before transcription until the model is present."
    }
  }

  Write-Step "Runtime restore complete"
}
finally {
  Pop-Location
}
