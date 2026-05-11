# Synpture

Synpture 是一个本地 Windows 工作台，用来把分享链接、本地音视频和文本文件整理成原稿、第一稿以及基于模板的深化结果。

当前主应用路径是：

- 后端：`FastAPI`
- 前端：`workspace-ui/`
- 开发启动：`python app.py`
- Windows 安装包：PyInstaller one-folder + Inno Setup

旧的 Streamlit 工作台已经不再作为主路径使用。

## 仓库应该提交什么

这个仓库应该保持“清爽源码仓库”：提交源码、脚本、测试、模板和小型 UI/品牌资源。

不要提交本机配置、用户数据、模型和运行时大资源：

- `.env`
- `output/`
- `models/`
- `third_party/chromium/`
- `third_party/ffmpeg/`
- `third_party/node/`
- `third_party/node_runtime/`
- `third_party/whisper.cpp/build-cuda/`
- `third_party/whisper.cpp/build-core/`
- `build/`
- `dist/`
- `dist-installer/`
- `Synpture/`

这些内容要么由恢复脚本在本机生成，要么由打包脚本生成。

## 环境要求

开发运行需要：

- Windows 10/11 x64
- PowerShell 5+
- Python 3.11+
- 首次恢复运行时资源需要网络

构建 Windows 安装包还需要：

- Visual Studio Build Tools，包含 C++ 工具链、CMake、Ninja
- 如果要重新构建 GPU 版 `whisper.cpp`，需要 NVIDIA CUDA Toolkit
- Inno Setup 6；如果没有，构建脚本会尝试通过 `winget` 安装

本地运行时资源包括：

- 固定版本的 `whisper.cpp` 源码
- 便携 Node.js
- Playwright package runtime
- Chrome for Testing / Chromium
- FFmpeg / FFprobe
- `whisper.cpp` GPU/CPU 运行时

模型文件：

```text
models/ggml-large-v3-turbo-q5_0.bin
```

模型不放进 Git。源码开发时可以手动放到 `models/`，也可以通过恢复脚本传入下载地址。

## 新电脑从源码恢复

从全新电脑或干净 clone 开始：

1. 安装基础工具：

   - Git for Windows
   - Python 3.11+
   - Visual Studio Build Tools，勾选 C++、CMake、Ninja
   - 需要 GPU 转录时安装 NVIDIA CUDA Toolkit

2. 克隆仓库：

   ```powershell
   git clone git@github.com:soilhao180/Synpture.git
   cd Synpture
   ```

3. 初始化开发环境：

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts/bootstrap_dev.ps1 -UseVenv
   ```

   这个脚本会创建 `.venv`、安装 Python 依赖、在缺少 `.env` 时从 `.env.example` 复制、恢复 `third_party/`、下载 Node/Chromium/FFmpeg、安装 Playwright、恢复 `whisper.cpp` 并准备本地转录运行时。

4. 添加转录模型：

   ```text
   models/ggml-large-v3-turbo-q5_0.bin
   ```

   如果你有模型直链，也可以运行：

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts/restore_runtime.ps1 -ModelUrl "https://example.com/ggml-large-v3-turbo-q5_0.bin"
   ```

5. 启动应用：

   ```powershell
   .\.venv\Scripts\Activate.ps1
   python app.py
   ```

6. 打开工作台：

   ```text
   http://127.0.0.1:8000
   ```

如果 `8000` 端口被占用，应用会自动使用下一个可用端口，并在终端输出实际地址。

## 快速启动

不创建虚拟环境：

```powershell
git clone git@github.com:soilhao180/Synpture.git
cd Synpture
powershell -ExecutionPolicy Bypass -File scripts/bootstrap_dev.ps1
python app.py
```

使用 `.venv`：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/bootstrap_dev.ps1 -UseVenv
.\.venv\Scripts\Activate.ps1
python app.py
```

默认地址：

```text
http://127.0.0.1:8000
```

## 只恢复运行时资源

如果 Python 依赖和 `.env` 已经准备好，只想恢复本地运行时：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/restore_runtime.ps1
```

如果模型缺失，并且你有模型直链：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/restore_runtime.ps1 -ModelUrl "https://example.com/ggml-large-v3-turbo-q5_0.bin"
```

如果模型已经手动放好：

```text
models/ggml-large-v3-turbo-q5_0.bin
```

恢复脚本会自动识别并继续。

## 配置文件

`.env` 是本机配置文件，不要提交到 Git。

首次启动或初始化时，如果 `.env` 不存在，会从 `.env.example` 创建。系统设置页面可以写回这些配置：

- API Base URL
- API Key
- 模型名
- 输出目录
- 运行时路径

主题偏好只存在前端本地状态里，不写入 `.env`。

## 常用命令

启动开发应用：

```powershell
python app.py
```

运行检查：

```powershell
node --check workspace-ui/src/app.js
python -m compileall app.py src tests synpture_launcher.py
python -m unittest discover -s tests -p "test_*.py" -v
```

恢复运行时：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/restore_runtime.ps1
```

## 构建安装包

默认构建 Lite 在线资源版：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_windows_installer.ps1 -Edition Lite
```

Lite 安装包不内置模型、Chromium/Playwright、FFmpeg、`whisper.cpp` 运行时。这些大资源会在首次使用对应功能时，从 GitHub Releases 下载到：

```text
%AppData%\Synpture
```

下载后必须通过 SHA256 校验，校验不通过不会放行使用。

如果本机已经恢复了完整 `models/` 和 `third_party/`，可以构建 Full 离线包：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_windows_installer.ps1 -Edition Full
```

安装器输出到：

```text
Synpture/SynptureSetup-Lite-x64.exe
Synpture/SynptureSetup-Full-x64.exe
```

## 发布 Lite 运行资源

Lite 版依赖 GitHub Releases 附件。需要上传这三个文件：

- `synpture-model-ggml-large-v3-turbo-q5_0.bin`
- `synpture-browser-runtime-win-x64.zip`
- `synpture-transcription-runtime-win-x64.zip`

本机有完整 `models/` 和 `third_party/` 时，可以生成附件和 SHA256 清单：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/package_runtime_assets.ps1
```

脚本输出到：

```text
Synpture/runtime-assets/
```

上传 Release 附件后，把 `SHA256SUMS.txt` 里的值填入：

```text
packaging/runtime_resources.json
```

注意：`runtime_resources.json` 里 SHA256 为空时，下载会被后端安全阻断。这是故意的，避免没有校验就下载运行二进制。

## 当前架构

重要后端文件：

- `app.py`
- `synpture_launcher.py`
- `src/presentation/web_app.py`
- `src/presentation/api_serializers.py`
- `src/presentation/task_registry.py`
- `src/runtime_paths.py`
- `src/runtime_resources.py`
- `src/diagnostics.py`
- `src/transcription_runtime.py`
- `src/application/pipeline_orchestrator.py`
- `src/infrastructure/artifact_store.py`

重要前端文件：

- `workspace-ui/index.html`
- `workspace-ui/src/app.js`
- `workspace-ui/src/styles.css`
- `workspace-ui/vendor/`
- `workspace-ui/SourceHanSansCN-VF-2.otf`

重要打包和恢复文件：

- `scripts/bootstrap_dev.ps1`
- `scripts/restore_runtime.ps1`
- `scripts/prepare_windows_runtime.ps1`
- `scripts/package_runtime_assets.ps1`
- `scripts/build_windows_installer.ps1`
- `packaging/runtime_resources.json`
- `packaging/synpture_launcher.spec`
- `packaging/SynptureInstaller.iss`

模板目录：

```text
templates/skills/
```

## 不能随便动的边界

- 不要把主工作台改回旧 Streamlit。
- 不要新增第二套前端栈。
- 保持 `python app.py` 可用。
- 保持 `FastAPI + workspace-ui` 主路径。
- 保持默认工具顺序：分享链接、本地媒体、文本输入、恢复项目。
- 不要把 `.env`、模型、用户 output、安装器产物、恢复出来的 `third_party` 大资源提交到 Git。
- CPU 转录兜底必须显式确认，不允许 GPU 失败后静默退到 CPU。
- 授权状态必须是真实检查结果，不允许伪造可用状态。

