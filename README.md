# Synpture

Synpture is a local Windows workspace for turning shared links, local media, and text files into structured transcripts, first-pass notes, and template-based outputs.

The current main app is:

- `FastAPI` backend
- `workspace-ui/` frontend
- single-command development start through `python app.py`
- Windows installer build through PyInstaller one-folder + Inno Setup

The old Streamlit workspace has been removed from the active codebase.

## What Belongs In Git

This repository should stay source-first and clean. Keep source, scripts, tests, templates, and small UI assets in Git.

Do not commit local runtime payloads or user data:

- `.env`
- `output/`
- `models/`
- `third_party/chromium/`
- `third_party/ffmpeg/`
- `third_party/node/`
- `third_party/node_runtime/`
- `third_party/whisper.cpp/build-cuda/`
- `third_party/whisper.cpp/build-core/`
- `dist/`
- `dist-installer/`
- `build/`

Those files are restored locally by scripts or produced by builds.

## Requirements

Required for development:

- Windows 10/11 x64
- PowerShell 5+
- Python 3.11+ available as `python`
- Internet access for first-time runtime restore

Required for Windows installer builds:

- Everything above
- Visual Studio Build Tools with C++ toolchain and CMake/Ninja support, for rebuilding `whisper.cpp`
- NVIDIA CUDA toolkit if rebuilding the GPU `whisper.cpp` runtime
- Inno Setup 6, or `winget` so the build script can install it

Runtime resources restored by scripts:

- `whisper.cpp` source at the pinned ref used by this project
- Node.js portable runtime
- Playwright package runtime
- Chrome for Testing / Chromium runtime
- FFmpeg / FFprobe
- `whisper.cpp` GPU runtime

Model file:

- `models/ggml-large-v3-turbo-q5_0.bin`

The model is intentionally not committed to Git. Put it in `models/`, or pass a download URL to the restore script.

## Fresh Clone Setup

From a clean clone:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/bootstrap_dev.ps1
```

Then start:

```powershell
python app.py
```

Default address:

```text
http://127.0.0.1:8000
```

If port `8000` is busy, the app will use the next available port and print the actual URL.

## Optional Virtual Environment

To let the bootstrap script create `.venv`:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/bootstrap_dev.ps1 -UseVenv
.\.venv\Scripts\Activate.ps1
python app.py
```

## Restoring Runtime Only

If Python dependencies and `.env` are already ready, restore only local runtime payloads:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/restore_runtime.ps1
```

If the model is missing and you have a direct download URL:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/restore_runtime.ps1 -ModelUrl "https://example.com/ggml-large-v3-turbo-q5_0.bin"
```

If you already placed the model manually:

```text
models/ggml-large-v3-turbo-q5_0.bin
```

the restore script will detect it and continue.

## Environment File

`.env` is local-only and must not be committed.

On first bootstrap, `.env` is copied from `.env.example`. The UI can write supported settings back to `.env`, including API base URL, API key, model name, output path, and runtime paths.

Theme preference is frontend local state and is not written to `.env`.

## Main Commands

Run development app:

```powershell
python app.py
```

Run checks:

```powershell
node --check workspace-ui/src/app.js
python -m compileall app.py src tests synpture_launcher.py
python -m unittest discover -s tests -p "test_*.py" -v
```

Restore runtime payloads:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/restore_runtime.ps1
```

This also restores `third_party/whisper.cpp` from the pinned upstream commit before building runtime binaries.

Build Windows installer:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_windows_installer.ps1
```

The installer is written to:

```text
dist-installer/SynptureSetup-x64.exe
```

## Current Architecture

Important backend files:

- `app.py`
- `synpture_launcher.py`
- `src/presentation/web_app.py`
- `src/presentation/api_serializers.py`
- `src/presentation/task_registry.py`
- `src/runtime_paths.py`
- `src/diagnostics.py`
- `src/transcription_runtime.py`
- `src/application/pipeline_orchestrator.py`
- `src/infrastructure/artifact_store.py`

Important frontend files:

- `workspace-ui/index.html`
- `workspace-ui/src/app.js`
- `workspace-ui/src/styles.css`
- `workspace-ui/vendor/`
- `workspace-ui/SourceHanSansCN-VF-2.otf`

Important packaging files:

- `scripts/bootstrap_dev.ps1`
- `scripts/restore_runtime.ps1`
- `scripts/prepare_windows_runtime.ps1`
- `scripts/build_windows_installer.ps1`
- `packaging/synpture_launcher.spec`
- `packaging/SynptureInstaller.iss`

Templates live in:

```text
templates/skills/
```

## Notes And Boundaries

- Do not reintroduce the old Streamlit UI as the main workspace.
- Do not add a second frontend stack.
- Keep `python app.py` working.
- Keep `FastAPI + workspace-ui` as the main path.
- Keep the default tool order: share link, local media, text input, recovery.
- Do not commit `.env`, models, user output, installer output, or restored `third_party` binaries.
- CPU transcription fallback must remain explicit; do not silently downgrade GPU failures to CPU.
- Auth status must remain real; do not replace browser checks with fake ready states.
