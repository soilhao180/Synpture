# Synpture Project Map

这份文档是未来分支开发用的项目导航图。它不替代 `README.md` 和 `HANDOFF.md`：

- `README.md`: 新机器恢复、运行、打包、发布资源的操作说明。
- `HANDOFF.md`: 阶段性交接背景和当时上下文。
- `PROJECT_MAP.md`: 稳定架构下的开发索引。先看这里，快速知道功能在哪、改哪里、跑什么命令、哪些边界不能破坏。

## Stable Shape

Synpture 当前稳定形态是本地 Windows 工作台：

| Area | Current path |
| --- | --- |
| Main app | `FastAPI + workspace-ui` |
| Dev entry | `python app.py` |
| Packaged entry | `synpture_launcher.py` packaged by PyInstaller |
| Frontend | `workspace-ui/index.html`, `workspace-ui/src/app.js`, `workspace-ui/src/styles.css` |
| Backend API | `src/presentation/web_app.py` |
| Pipeline core | `src/application/pipeline_orchestrator.py` |
| Installer | PyInstaller one-folder + Inno Setup |

Do not reintroduce Streamlit as the main UI path. Do not add a second frontend stack unless the whole architecture is explicitly being replaced.

## Command Cheat Sheet

Run the development app:

```powershell
python app.py
```

Run syntax and regression checks:

```powershell
node --check workspace-ui/src/app.js
python -m compileall app.py src tests synpture_launcher.py
python -m unittest discover -s tests -p "test_*.py" -v
```

Restore local runtime resources:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/restore_runtime.ps1
```

Bootstrap a new dev environment:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/bootstrap_dev.ps1 -UseVenv
.\.venv\Scripts\Activate.ps1
python app.py
```

Build the Lite installer:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_windows_installer.ps1 -Edition Lite
```

Build the Full installer when local `models/` and `third_party/` resources are complete:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_windows_installer.ps1 -Edition Full
```

Package Lite runtime assets for GitHub Releases:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/package_runtime_assets.ps1
```

## Architecture Map

| Subsystem | Main files | What lives here |
| --- | --- | --- |
| Entrypoints | `app.py`, `synpture_launcher.py` | Dev server startup, packaged tray/app launcher, browser open/close lifecycle, port selection. |
| API and workspace backend | `src/presentation/web_app.py` | FastAPI app, route definitions, task submission, settings endpoints, runtime resources endpoints, health/self-check endpoints. |
| API serialization | `src/presentation/api_serializers.py` | Converts internal models into frontend JSON payloads for bootstrap, run workspace, health, settings, templates, downloads. |
| Settings writeback | `src/presentation/config_io.py`, `src/config.py` | `.env` loading and safe settings persistence. Keep secret handling here. |
| Frontend app | `workspace-ui/src/app.js` | Single-page UI state, render functions, action handlers, API calls, task polling, runtime gates. |
| Frontend styling | `workspace-ui/src/styles.css` | Design system, drawer/card/button/input states, responsive behavior, light/dark theme rules. |
| Task execution | `src/presentation/task_registry.py`, `src/domain/job.py`, `src/application/status.py` | Background task lifecycle, cancellation, snapshots, progress state. |
| Pipeline orchestration | `src/application/pipeline_orchestrator.py`, `src/services/*` | Main job flow: acquire source, transcribe if needed, summarize, write artifacts, resume stages. |
| Input acquisition | `src/source_ingest.py`, `src/share_link_ingest.py`, `src/link_ingest/*` | Local media/text ingestion, share-link probing/downloading, platform detection, subtitle parsing, auth browser support. |
| Transcription | `src/transcriber.py`, `src/transcribers/whisper_cpp.py`, `src/transcription_runtime.py` | Local whisper.cpp execution, GPU/CPU runtime probing, explicit CPU fallback decision, GPU diagnostics. |
| Summary and templates | `src/summarizer.py`, `src/summarizers/*`, `src/template_registry.py`, `templates/skills/*` | First-pass summaries, template pass, OpenAI-compatible backend, runtime template catalog. |
| Persistence | `src/infrastructure/artifact_store.py`, `src/artifacts.py`, `src/result_writers.py` | Output run directories, manifest/artifact load/save, markdown/doc artifacts. |
| Runtime paths/resources | `src/runtime_paths.py`, `src/runtime_resources.py`, `src/diagnostics.py` | Dev vs packaged paths, `%AppData%\Synpture`, Lite resource manifest, download/install/check state, self-check items. |
| Packaging | `scripts/*`, `packaging/*`, `tools/build_whisper_cpp.cmd` | Runtime restore/provision, installer build, runtime asset packaging, PyInstaller and Inno Setup config. |

## Where to Change X

| Change needed | Start here | Also check |
| --- | --- | --- |
| Add or adjust a frontend view | `workspace-ui/src/app.js` | `workspace-ui/src/styles.css`, API payload in `api_serializers.py` |
| Change visual spacing/theme/drawer behavior | `workspace-ui/src/styles.css` | Render markup in `workspace-ui/src/app.js` |
| Add a button/action in UI | `workspace-ui/src/app.js` | `handleAction()`, `isActionDisabled()`, related API route |
| Add or change an API route | `src/presentation/web_app.py` | Serializer in `api_serializers.py`, tests in `test_web_app_api.py` |
| Change task lifecycle/progress/cancel | `src/presentation/task_registry.py` | `src/domain/job.py`, `src/application/status.py`, frontend polling in `app.js` |
| Change main pipeline flow | `src/application/pipeline_orchestrator.py` | `src/services/*`, `src/infrastructure/artifact_store.py` |
| Change local media/text ingestion | `src/source_ingest.py` | `tests/test_core.py`, `tests/test_architecture_v2.py` |
| Change share-link ingestion/auth | `src/share_link_ingest.py` | `src/link_ingest/*`, browser runtime checks, `tests/test_link_ingest.py` |
| Change transcription backend selection | `src/transcription_runtime.py` | `src/transcriber.py`, `tests/test_transcription_runtime.py` |
| Change whisper.cpp parsing/execution | `src/transcribers/whisper_cpp.py` | `src/transcriber.py`, `tests/test_core.py` |
| Change summary/model/template behavior | `src/summarizer.py` | `src/summarizers/*`, `src/template_registry.py`, `templates/skills/*` |
| Change output/recovery behavior | `src/infrastructure/artifact_store.py` | `src/artifacts.py`, `src/presentation/state.py`, recovery tests |
| Change runtime resource install/download | `src/runtime_resources.py` | `packaging/runtime_resources.json`, frontend runtime resource UI |
| Change health self-check | `src/diagnostics.py` | `src/presentation/web_app.py`, `workspace-ui/src/app.js` |
| Change packaged path behavior | `src/runtime_paths.py` | `tests/test_runtime_paths*.py`, installer script |
| Change Lite/Full installer behavior | `scripts/build_windows_installer.ps1` | `packaging/synpture_launcher.spec`, `packaging/SynptureInstaller.iss` |
| Change release runtime assets | `scripts/package_runtime_assets.ps1` | `packaging/runtime_resources.json`, SHA256 values |

## Frontend Design Rules

Synpture is a workstation UI, not a marketing site. New UI should stay dark by default, restrained, operational, readable, and stable during repeated use.

### Layout and Gutters

- Page padding comes from root variables: top `28px`, left/right `32px`, bottom `32px`.
- The main shell is centered and capped at `1856px`.
- The center work area has a stable `1200px` meaning. Do not casually widen the primary task surface.
- The workspace grid is: left rail / `32px` gutter / `1200px` center / `32px` gutter / right rail.
- Side rails are `296px` by default. When viewport width is tight, drawers may overlay content instead of crushing the center.
- Main module spacing should use `20px` or `24px`. Drawer cards stack with `18px`.

### Spacing Scale

- Use the existing spacing tokens: `6, 8, 10, 12, 14, 16, 18, 20, 24, 28, 32, 40px`.
- Form internals generally use `12px` vertical gap.
- Primary content cards use `24px` padding.
- Drawer cards use `14px` to `16px` padding.
- Compact list/status items use `12px` to `14px` padding.
- Button rows use `10px` gap; narrow drawer button groups become one-column grids with `8px` gap.
- Avoid one-off values like `17px`, `23px`, or `37px` unless there is a measured reason.

### Alignment

- Header rows with a title plus status/action use `grid-template-columns: minmax(0, 1fr) auto`.
- Long text goes in the flexible left column. Status chips, buttons, percentages, and icons stay in fixed right columns.
- Status chips must not be squeezed into two lines. Give them stable `min-width`, `min-height`, and `white-space: nowrap`.
- Drawer header actions stay in the top-right. The title area may wrap or truncate.
- Forms use label-above-input. Do not switch settings or upload controls to side-by-side label/input layout.
- Paths, filenames, errors, and runtime details must use wrapping rules such as `overflow-wrap: anywhere` so they never break card boundaries.

### Radius

- Major cards, drawers, and content blocks use `20px`.
- Inner cards, upload areas, and status blocks use `16px`.
- Buttons, icon buttons, inputs, and small controls use `14px`.
- Pills, chips that are intentionally pill-shaped, progress bars, and dots use `999px`.
- Do not introduce a softer marketing-style radius system.

### Surfaces and Cards

- The default background is deep blue-black, never pure black.
- Surfaces use a dark fill, `1px` border, subtle inner highlight, and restrained shadow.
- Cards are for actual containers: main views, drawers, repeated items, status items, and modals. Avoid deep card-in-card nesting.
- Drawer repeated items may be compact cards, but spacing must stay tight and scannable.
- The main accent is capture green (`#44e0c7`). Do not introduce large new color families for status or decoration.

### Typography

- Use `Source Han Sans CN` first, then `PingFang SC`, `Microsoft YaHei`, `sans-serif`.
- Main view titles are around `30px`; drawer/panel titles around `22px`; surface titles around `18px`; compact item titles around `13px`.
- Most body/help text is `12px` with `1.65` to `1.75` line-height.
- Drawer descriptions, health details, and runtime notes should stay compact and readable, not hero-sized.
- Do not use negative letter spacing. Eyebrow text may use uppercase and modest letter spacing.

### Controls

- Primary buttons are at least `40px` high; narrow drawer buttons are at least `38px`.
- Icon buttons are fixed at `42px x 42px`.
- Upload controls need a clear icon area, label, and current value; do not reduce them to plain text buttons.
- Hover motion is a light `translateY(-1px)`. Avoid glow-heavy or large movement interactions.
- Busy/loading states must keep button dimensions stable so the layout does not jump when labels change.

### Responsive and Overflow

- Prefer CSS Grid for fixed-format tool layouts. Avoid complex flex percentage math.
- Fixed-format UI elements need stable dimensions: status chips, toolbar buttons, upload controls, progress bars, drawer headers.
- Long paths, filenames, errors, and resource details must wrap inside their parent.
- In narrow drawers, action groups should become one-column grids; do not force multiple long buttons into one row.
- After UI changes, check for text overflow, chip deformation, button wrapping, and long path overflow in both dark and light themes.

### Theme

- Dark mode is the default.
- Light mode should preserve the same layout semantics and only swap colors/surface treatment.
- Keep the accent centered on `#44e0c7`.
- Do not add purple-blue gradients, neon outer glows, decorative blobs, or ornamental background orbs.

### Product Boundaries

- This is a workstation, not a landing page.
- Do not add a second UI framework.
- Do not add cute illustrations, marketing hero sections, or decorative-first layouts.
- Runtime resources, self-check, auth, and GPU states must be direct and truthful. Do not duplicate the same error in multiple sections of one screen.

## Runtime and Data Map

| Path | Meaning | Git policy |
| --- | --- | --- |
| `.env` | Local settings written by setup or settings UI. Contains local API configuration. | Do not commit. Do not paste secrets into docs/tests. |
| `.env.example` | Safe defaults/template for local `.env`. | Commit. Keep generic. |
| `output/` | User run outputs, manifests, transcripts, summaries, recovery data. | Do not commit. |
| `models/` | Local whisper model files, especially `ggml-large-v3-turbo-q5_0.bin`. | Do not commit model binaries. |
| `third_party/` | Local dev runtime: Node, Chromium, FFmpeg, whisper.cpp source/builds. | Do not commit restored large runtime outputs. |
| `%AppData%\Synpture` | Packaged/Lite user data root and downloaded runtime resources. | Outside repo; never assume source-tree paths in packaged mode. |
| `Synpture/` | Installer output directory, including `SynptureSetup-*-x64.exe`. | Build artifact; do not commit. |
| `build/`, `dist/` | PyInstaller build outputs. | Build artifacts; do not commit. |
| `templates/skills/` | Runtime summary/template definitions. | Commit; this is product behavior. |
| `workspace-ui/vendor/` | Vendored frontend runtime files used by the static UI. | Commit when intentionally updated. |

Lite resources are controlled by `packaging/runtime_resources.json` and exposed through the runtime resource API. The three stable resource ids are:

| Resource id | Required for | Installed content |
| --- | --- | --- |
| `model` | transcription | `models/ggml-large-v3-turbo-q5_0.bin` |
| `browser_runtime` | share-link auth/probing | Node, Playwright package runtime, Chromium |
| `transcription_runtime` | local transcription | FFmpeg/FFprobe, whisper.cpp GPU/CPU runtime |

## API Surface

The FastAPI app is built in `src/presentation/web_app.py`. Route handlers should stay thin: validate request, call backend/service, serialize response.

| Group | Routes |
| --- | --- |
| Bootstrap | `GET /api/bootstrap` |
| Runs/history | `GET /api/runs`, `GET /api/runs/{run_id}`, `GET /api/runs/{run_id}/download/{artifact_name}` |
| Task creation | `POST /api/tasks/share-link`, `POST /api/tasks/local-media`, `POST /api/tasks/text-file`, `POST /api/tasks/pasted-text`, `POST /api/tasks/recovery/uploaded-dir` |
| Task lifecycle | `GET /api/tasks/{task_id}/status`, `POST /api/tasks/{task_id}/cancel` |
| Resume/template work | `POST /api/runs/{run_id}/resume-first-pass`, `POST /api/runs/{run_id}/resume-templates`, `POST /api/runs/{run_id}/templates/{template_id}` |
| Health/runtime | `GET /api/health`, `POST /api/health/run`, `GET /api/runtime/status`, `GET /api/runtime/transcription-capability`, `POST /api/runtime/transcription-preference` |
| Runtime resources | `GET /api/runtime/resources`, `POST /api/runtime/resources/{resource_id}/download`, `GET /api/runtime/resources/{resource_id}/status`, `POST /api/runtime/resources/{resource_id}/upload` |
| Settings | `GET /api/settings`, `POST /api/settings`, `POST /api/settings/test-connection`, `GET /api/settings/models`, `POST /api/settings/models`, `POST /api/settings/test-model` |
| Auth browser | `POST /api/auth/{platform}/open`, `GET /api/auth/{platform}/status` |
| Frontend session | `GET /api/runtime/frontend-session`, `POST /api/runtime/frontend-session/open`, `POST /api/runtime/frontend-session/heartbeat`, `POST /api/runtime/frontend-session/close` |
| Shutdown/static | `POST /api/runtime/shutdown`, `GET /`, `GET /index.html` |

## Testing Map

| Test file | Covers |
| --- | --- |
| `tests/test_web_app_api.py` | FastAPI routes, settings, runtime resources, task API behavior. |
| `tests/test_architecture_v2.py` | Service/pipeline architecture and artifact round trips. |
| `tests/test_core.py` | Core transcription, diagnostics, segmenting, source ingest, result writing. |
| `tests/test_workspace_refactor.py` | Workspace state, `.env` writeback, run list/recovery behavior. |
| `tests/test_runtime_resources.py` | Runtime resource manifest/status/download/install behavior. |
| `tests/test_runtime_paths.py`, `tests/test_runtime_paths_packaged_layout.py` | Dev vs packaged path behavior and runtime defaults. |
| `tests/test_transcription_runtime.py` | GPU/CPU transcription capability probing and effective runtime resource paths. |
| `tests/test_diagnostics_runtime_resources.py` | Browser/runtime diagnostics using effective resource paths. |
| `tests/test_link_ingest.py` | Share-link ingestion, platform support, auth profile checks, bundled browser runtime. |
| `tests/test_project3_flow.py` | Template registry, first-pass/template artifacts, resume detection. |
| `tests/test_synpture_launcher.py` | Packaged launcher, frontend session lifecycle, tray/browser behavior. |
| `tests/test_server_boot.py` | Uvicorn/server boot helpers. |

Minimum checks for frontend-only edits:

```powershell
node --check workspace-ui/src/app.js
```

Minimum checks for backend-only edits:

```powershell
python -m compileall app.py src tests synpture_launcher.py
python -m unittest discover -s tests -p "test_*.py" -v
```

Full pre-package checks:

```powershell
node --check workspace-ui/src/app.js
python -m compileall app.py src tests synpture_launcher.py
python -m unittest discover -s tests -p "test_*.py" -v
```

Installer smoke build:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_windows_installer.ps1 -Edition Lite
```

## Hard Boundaries

- Keep `python app.py` working as the development entry.
- Keep `FastAPI + workspace-ui` as the main product path.
- Do not return to Streamlit as the main workspace.
- Do not add another frontend framework or duplicate workspace UI.
- Do not commit `.env`, API keys, `output/`, model binaries, restored `third_party` runtimes, or installer/build outputs.
- Do not fake auth/resource/GPU states. Status must come from real checks.
- CPU transcription fallback must be explicit; do not silently fall back from GPU failure to CPU.
- Packaged mode must not rely on source-tree-only paths; use `runtime_paths.py` and runtime resource helpers.
- Lite runtime downloads must keep SHA256 validation. Empty or mismatched SHA should block use.
- Settings writeback must preserve `.env` safety rules and must not create multiline secrets.
- UI changes should preserve the existing single-page app structure, drawer semantics, tool order, and responsive constraints.

## Development Flow for New Branches

1. Read this file first, then only inspect the subsystem you need.
2. Check `git status --short` before editing.
3. Locate the feature in `Where to Change X`.
4. Make the smallest coherent change inside the existing architecture.
5. Run the matching tests from `Testing Map`.
6. If installer/runtime behavior changed, rebuild Lite and verify the installer output path.
