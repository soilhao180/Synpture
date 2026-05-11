param(
  [string]$OutputDir = "",
  [string]$ModelPath = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
if (-not $OutputDir) {
  $OutputDir = Join-Path $root "Synpture\runtime-assets"
}
if (-not $ModelPath) {
  $ModelPath = Join-Path $root "models\ggml-large-v3-turbo-q5_0.bin"
}

$browserRuntimeRoot = Join-Path $root "third_party"
$transcriptionRuntimeRoot = Join-Path $root "third_party"
$stageRoot = Join-Path $root "build\runtime-assets-stage"
$browserStage = Join-Path $stageRoot "browser_runtime"
$transcriptionStage = Join-Path $stageRoot "transcription_runtime"

function Assert-PathExists {
  param(
    [string]$PathToCheck,
    [string]$Message
  )
  if (-not (Test-Path $PathToCheck)) {
    throw $Message
  }
}

function Copy-Directory {
  param(
    [string]$Source,
    [string]$Destination
  )
  Assert-PathExists $Source "Missing runtime asset source: $Source"
  New-Item -ItemType Directory -Path (Split-Path -Parent $Destination) -Force | Out-Null
  Copy-Item $Source $Destination -Recurse -Force
}

function Write-HashLine {
  param(
    [string]$FilePath,
    [string]$HashFile
  )
  $hash = (Get-FileHash -Algorithm SHA256 $FilePath).Hash.ToLowerInvariant()
  Add-Content -Path $HashFile -Value ("{0}  {1}" -f $hash, (Split-Path -Leaf $FilePath)) -Encoding utf8
}

New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
if (Test-Path $stageRoot) {
  Remove-Item $stageRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $browserStage -Force | Out-Null
New-Item -ItemType Directory -Path $transcriptionStage -Force | Out-Null

$modelAsset = Join-Path $OutputDir "synpture-model-ggml-large-v3-turbo-q5_0.bin"
$browserAsset = Join-Path $OutputDir "synpture-browser-runtime-win-x64.zip"
$transcriptionAsset = Join-Path $OutputDir "synpture-transcription-runtime-win-x64.zip"
$hashFile = Join-Path $OutputDir "SHA256SUMS.txt"

Assert-PathExists $ModelPath "Missing model file: $ModelPath"
Copy-Item $ModelPath $modelAsset -Force

Copy-Directory (Join-Path $browserRuntimeRoot "node") (Join-Path $browserStage "node")
Copy-Directory (Join-Path $browserRuntimeRoot "node_runtime") (Join-Path $browserStage "node_runtime")
Copy-Directory (Join-Path $browserRuntimeRoot "chromium") (Join-Path $browserStage "chromium")

Copy-Directory (Join-Path $transcriptionRuntimeRoot "ffmpeg") (Join-Path $transcriptionStage "ffmpeg")
Copy-Directory (Join-Path $transcriptionRuntimeRoot "whisper.cpp\build-cuda\bin") (Join-Path $transcriptionStage "whisper.cpp\build-cuda\bin")
Copy-Directory (Join-Path $transcriptionRuntimeRoot "whisper.cpp\build-core\bin") (Join-Path $transcriptionStage "whisper.cpp\build-core\bin")

if (Test-Path $browserAsset) {
  Remove-Item $browserAsset -Force
}
if (Test-Path $transcriptionAsset) {
  Remove-Item $transcriptionAsset -Force
}
Compress-Archive -Path (Join-Path $browserStage "*") -DestinationPath $browserAsset -CompressionLevel Optimal
Compress-Archive -Path (Join-Path $transcriptionStage "*") -DestinationPath $transcriptionAsset -CompressionLevel Optimal

if (Test-Path $hashFile) {
  Remove-Item $hashFile -Force
}
Write-HashLine $modelAsset $hashFile
Write-HashLine $browserAsset $hashFile
Write-HashLine $transcriptionAsset $hashFile

Write-Host "Runtime assets written to: $OutputDir"
Write-Host "Update packaging/runtime_resources.json with the SHA256 values from: $hashFile"
