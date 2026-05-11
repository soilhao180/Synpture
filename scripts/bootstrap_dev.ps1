param(
  [string]$Python = "python",
  [string]$NodeMajor = "22",
  [string]$ModelUrl = "",
  [string]$WhisperCppRef = "fc674574ca27cac59a15e5b22a09b9d9ad62aafe",
  [switch]$UseVenv,
  [switch]$ForceRuntime,
  [switch]$SkipRuntimeProvision,
  [switch]$SkipWhisperSource,
  [switch]$SkipModel
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$requirementsPath = Join-Path $root "requirements.txt"
$envExamplePath = Join-Path $root ".env.example"
$envPath = Join-Path $root ".env"
$restoreRuntimeScript = Join-Path $root "scripts\restore_runtime.ps1"
$venvPython = Join-Path $root ".venv\Scripts\python.exe"

function Write-Step {
  param([string]$Message)
  Write-Host ""
  Write-Host "==> $Message" -ForegroundColor Cyan
}

function Resolve-PythonCommand {
  if ($UseVenv) {
    if (-not (Test-Path -LiteralPath $venvPython)) {
      Write-Step "Creating local virtual environment"
      & $Python -m venv (Join-Path $root ".venv")
      if ($LASTEXITCODE -ne 0) {
        throw "Failed to create virtual environment."
      }
    }
    return $venvPython
  }
  return $Python
}

Push-Location $root
try {
  Write-Step "Checking Python"
  $pythonCmd = Resolve-PythonCommand
  & $pythonCmd --version
  if ($LASTEXITCODE -ne 0) {
    throw "Python is not available. Install Python 3.11+ and retry."
  }

  Write-Step "Installing Python dependencies"
  if (-not (Test-Path -LiteralPath $requirementsPath)) {
    throw "Missing requirements.txt: $requirementsPath"
  }
  & $pythonCmd -m pip install --upgrade pip
  if ($LASTEXITCODE -ne 0) {
    throw "Failed to upgrade pip."
  }
  & $pythonCmd -m pip install -r $requirementsPath
  if ($LASTEXITCODE -ne 0) {
    throw "Failed to install Python dependencies."
  }

  Write-Step "Preparing .env"
  if (-not (Test-Path -LiteralPath $envPath)) {
    if (-not (Test-Path -LiteralPath $envExamplePath)) {
      throw "Missing .env.example: $envExamplePath"
    }
    Copy-Item -LiteralPath $envExamplePath -Destination $envPath
    Write-Host "Created .env from .env.example"
  }
  else {
    Write-Host ".env already exists; keeping your local settings."
  }

  Write-Step "Restoring runtime resources"
  $restoreArgs = @(
    "-ExecutionPolicy", "Bypass",
    "-File", $restoreRuntimeScript,
    "-Python", $pythonCmd,
    "-NodeMajor", $NodeMajor,
    "-WhisperCppRef", $WhisperCppRef
  )
  if ($ModelUrl.Trim()) {
    $restoreArgs += @("-ModelUrl", $ModelUrl.Trim())
  }
  if ($ForceRuntime) {
    $restoreArgs += "-Force"
  }
  if ($SkipRuntimeProvision) {
    $restoreArgs += "-SkipRuntimeProvision"
  }
  if ($SkipWhisperSource) {
    $restoreArgs += "-SkipWhisperSource"
  }
  if ($SkipModel) {
    $restoreArgs += "-SkipModel"
  }
  & powershell @restoreArgs
  if ($LASTEXITCODE -ne 0) {
    throw "Runtime restore failed."
  }

  Write-Step "Bootstrap complete"
  Write-Host "Start Synpture with:"
  if ($UseVenv) {
    Write-Host "  .\.venv\Scripts\Activate.ps1"
  }
  Write-Host "  python app.py"
}
finally {
  Pop-Location
}
