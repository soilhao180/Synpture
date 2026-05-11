# Synpture 源码清理交接文档

这份文档用于在删除旧仓库、清理本地项目目录、重新建立新仓库前判断哪些路径能碰、哪些路径不能碰、哪些少了会直接导致应用或安装包不可用。

当前判断基于现有主线：`FastAPI + workspace-ui`。默认入口仍是：

```powershell
python app.py
```

Windows 安装版入口是：

```powershell
synpture_launcher.py
```

## 一句话结论

必须保留的是：`app.py`、`synpture_launcher.py`、`src/` 当前 FastAPI 与流水线代码、`workspace-ui/` 当前前端、`templates/skills/`、`assets/branding/`、`assets/start-page/`、`tools/*browser*.js`、`packaging/`、`scripts/build_windows_installer.ps1`、`scripts/prepare_windows_runtime.ps1`、`.env.example`、`requirements.txt`。

可以清理的是：`build/`、`dist/`、`dist-installer/`、`__pycache__/`、`workspace-ui/node_modules/`、截图临时文件、`output/` 历史产物、`third_party/playwright-browsers/`、`third_party/downloads/`。

大资源不要进新仓库：`models/`、`third_party/chromium/`、`third_party/ffmpeg/`、`third_party/node/`、`third_party/node_runtime/`、`third_party/whisper.cpp/`。它们应由构建脚本下载、生成或由 release 附件/安装包流程管理。

## 当前主架构

- `app.py`：开发和调试默认入口，创建 FastAPI 应用并启动 uvicorn。
- `src/presentation/web_app.py`：FastAPI 路由、静态资源挂载、任务入口、设置、自检、授权、运行时接口。
- `workspace-ui/`：正式前端工作台。当前不是旧 Streamlit 工作台。
- `synpture_launcher.py`：Windows 安装版桌面启动器，负责启动后端、托盘菜单、浏览器打开、关闭后端。
- `packaging/synpture_launcher.spec`：PyInstaller one-folder 配置。
- `packaging/SynptureInstaller.iss`：Inno Setup 安装器配置。

## 少了会直接死的路径

### 后端源码

这些是当前主链路必需：

- `app.py`
- `synpture_launcher.py`
- `src/config.py`
- `src/runtime_paths.py`
- `src/server_boot.py`
- `src/diagnostics.py`
- `src/transcription_runtime.py`
- `src/transcriber.py`
- `src/transcribers/`
- `src/share_link_ingest.py`
- `src/source_ingest.py`
- `src/template_registry.py`
- `src/summarizer.py`
- `src/summarizers/`
- `src/models.py`
- `src/utils.py`
- `src/progress.py`
- `src/result_writers.py`
- `src/artifacts.py`
- `src/application/`
- `src/services/`
- `src/infrastructure/`
- `src/link_ingest/`
- `src/presentation/web_app.py`
- `src/presentation/api_serializers.py`
- `src/presentation/config_io.py`
- `src/presentation/runtime_snapshot.py`
- `src/presentation/state.py`
- `src/presentation/task_registry.py`

删错后常见表现：

- `/` 打不开或静态资源 404。
- `/api/bootstrap` 报错。
- 分享链接、本地媒体、文本输入、恢复项目入口无法创建任务。
- 系统设置无法读取或保存。
- 自检无法运行。
- 授权浏览器无法打开。
- 项目历史和恢复项目丢失。

### 前端正式工作台

这些是当前正式前端，不是 mock：

- `workspace-ui/index.html`
- `workspace-ui/src/app.js`
- `workspace-ui/src/styles.css`
- `workspace-ui/assets/icons/Frame_11.svg`
- `workspace-ui/assets/icons/start-page-logo.svg`
- `workspace-ui/vendor/ogl/`
- `workspace-ui/SourceHanSansCN-VF-2.otf`

注意：

- `workspace-ui/src/app.js` 是当前真实 API 前端。
- `workspace-ui/src/styles.css` 是当前真实样式。
- `workspace-ui/vendor/ogl/` 是首屏 Aurora 背景运行时，不能只保留 `package.json` 然后删掉 vendor。
- `workspace-ui/node_modules/` 可以删，当前正式运行不依赖它。

### 模板系统

这些是模板深化功能必需：

- `templates/skills/*/template.json`
- `templates/skills/*/SKILL.md`
- `templates/skills/*/agents/openai.yaml`

少了以后：

- 模板列表为空。
- 第一稿之后无法做模板深化。
- 已有项目的模板结果仍可能能读，但无法新生成对应模板。

### 共享资源和品牌资源

这些被安装器、托盘或首屏直接引用：

- `assets/branding/synpture-app.ico`
- `assets/branding/synpture-tray.png`
- `assets/branding/icon-master.svg`
- `assets/start-page/Frame-10.svg`
- `assets/start-page/frame-8.png`

少了以后：

- 安装器图标、桌面图标、托盘图标异常。
- 首屏进入按钮资源缺失。

### 授权浏览器脚本

这些是分享链接授权和探测链路必需：

- `tools/share_link_auth_browser.js`
- `tools/share_link_browser_probe.js`
- `tools/douyin_browser_probe.js`

少了以后：

- 抖音/B 站授权打开失败。
- 授权状态检查失败。
- 新电脑上点击授权可能又变成“看似打开但没反应”。

### 打包脚本

这些是 Windows 安装包链路必需：

- `scripts/prepare_windows_runtime.ps1`
- `scripts/build_windows_installer.ps1`
- `packaging/synpture_launcher.spec`
- `packaging/SynptureInstaller.iss`

少了以后：

- 无法重建 one-folder。
- 无法生成 `SynptureSetup-x64.exe`。
- 无法补齐 Node、Chromium、ffmpeg、whisper.cpp 等运行时。

## 运行时资源：不建议进源码仓库，但安装包需要

这些目录体积大，建议不要提交到新仓库。它们应通过构建脚本、release 附件、安装器资源、首次下载机制来管理。

### 模型

- `models/ggml-large-v3-turbo-q5_0.bin`

当前如果不改代码，它是默认转录模型路径。少了以后：

- GPU/CPU 转录都会提示模型缺失。
- 本地媒体和分享链接转录不能继续。

建议后续改造：

- 不把模型放进默认安装包。
- 首次转录时提示下载模型或选择已有模型。
- 下载后放到 `%AppData%\Synpture\models\`。

### 浏览器运行时

- `third_party/chromium/`

当前安装版授权链路实际使用：

- `third_party/chromium/chrome.exe`

少了以后：

- 新电脑没有 Chrome/Chromium 时，授权浏览器打不开。
- 自检会显示浏览器运行时缺失。

可以删的是：

- `third_party/playwright-browsers/`

原因：

- 当前业务代码显式使用 `SHARE_LINK_CHROME_EXE`。
- Node 脚本通过 Playwright 的 `executablePath` 启动 `third_party/chromium/chrome.exe`。
- `playwright-browsers` 是 Playwright 下载浏览器缓存，不是当前运行时必需项。

### Node 与 Playwright 库

- `third_party/node/`
- `third_party/node_runtime/node_modules/`

少了以后：

- 分享链接授权脚本无法运行。
- 浏览器探针无法运行。

注意：

- `third_party/node_runtime/node_modules/playwright` 是 Playwright 控制库，不能和 `third_party/playwright-browsers` 混为一谈。
- `node_runtime/node_modules` 需要保留在安装包里，但不建议提交到源码仓库。

### ffmpeg

- `third_party/ffmpeg/bin/ffmpeg.exe`
- `third_party/ffmpeg/bin/ffprobe.exe`
- 以及运行它们所需 DLL

少了以后：

- 本地媒体抽音频失败。
- 分享链接下载后合并/处理媒体失败。

可以考虑精简：

- 不需要 `ffplay.exe`。
- 不需要文档、示例、开发头文件。

### whisper.cpp

当前路径约定：

- GPU：`third_party/whisper.cpp/build-cuda/bin/whisper-cli.exe`
- CPU：`third_party/whisper.cpp/build-core/bin/whisper-cli.exe`

少了以后：

- GPU 转录不可用。
- 如果 CPU 版也少了，显式 CPU 兜底也不可用。

建议新仓库策略：

- 源码仓库不提交完整 `third_party/whisper.cpp` 构建产物。
- 只保留构建脚本和必要说明。
- release/安装器阶段再放入 exe/DLL。

## 可以直接清理的本地产物

这些一般不是源码，也不应进入新仓库：

- `build/`
- `dist/`
- `dist-installer/`
- `__pycache__/`
- `src/**/__pycache__/`
- `workspace-ui/node_modules/`
- `output/`
- `.adnify/`
- `.env`
- `third_party/downloads/`
- `third_party/playwright-browsers/`
- 根目录 `_tmp_*.png`
- 根目录 `frame7_*.png`
- 根目录 `project_home*.png`
- 根目录 `start_page_after_button_swap.png`
- 根目录 `_inspect_main.txt`
- `workspace-ui/.tmp-*.png`

注意：

- `output/` 是用户历史项目和恢复项目来源。清理源码仓库时可以排除，但如果你还想保留测试样本或用户数据，要先单独备份。
- `.env` 不进仓库，只保留 `.env.example`。
- `dist-installer/SynptureSetup-x64.exe` 是构建产物，不进源码仓库；发布时走 release artifact。

## 已删除的旧 Streamlit 代码

当前主工作台已经不是 Streamlit。以下旧 Streamlit 视图代码已经从源码树删除：

- `src/presentation/workspace.py`
- `src/presentation/workspace_shell.py`
- `src/presentation/components.py`
- `src/presentation/styles.py`
- `src/presentation/runtime.py`
- `src/presentation/design_tokens.py`
- `src/presentation/views/`

同时已经从 `requirements.txt` 删除 `streamlit` 依赖。

保留边界：

- 不要重新引入旧 Streamlit UI。
- 不要把 `python app.py` 改回 `streamlit run app.py`。
- 如需查看旧实现，使用外部备份，不要把旧代码重新混入主线。

删除后必须跑：

```powershell
node --check workspace-ui/src/app.js
python -m compileall app.py src tests synpture_launcher.py
python -m unittest discover -s tests -p "test_*.py" -v
```

## 已删除的旧前端/设计稿文件

这些文件不是正式运行主路径，已经删除：

- `workspace-ui/src/main.js`
- `workspace-ui/src/mock-data.js`
- `workspace-ui/src/runtime-data.js`
- `index.html` 根目录文件
- 根目录 `SourceHanSansCN-VF-2.otf`

当前判断：

- `workspace-ui/src/app.js` 是正式前端入口。
- `workspace-ui/index.html` 是正式 HTML 入口。
- 正式 CSS 引用的是 `workspace-ui/SourceHanSansCN-VF-2.otf`，不是根目录字体。
- `src/presentation/runtime_snapshot.py` 仍保留快照构建函数用于测试/调试，但不再默认输出到 `workspace-ui/src/runtime-data.js`。

## 文档状态

当前仍有价值的文档：

- `README.md`
- `docs/workspace-handover.md`
- `docs/project3-fixed-summary-template-prd.md`
- `docs/cleanup-handover.md`

已经删除的旧文档：

- `docs/setup-windows.md`
- `docs/project0-link-ingest.md`
- `docs/douyin-browser-profile-lab.md`

## 建议的新仓库初始结构

推荐只把这些作为新仓库第一版：

```text
app.py
synpture_launcher.py
requirements.txt
README.md
.env.example
.gitignore
assets/
docs/
packaging/
scripts/
src/
templates/
tests/
tools/
workspace-ui/
package.json
package-lock.json
```

但需要排除：

```text
build/
dist/
dist-installer/
output/
models/
third_party/chromium/
third_party/ffmpeg/
third_party/node/
third_party/node_runtime/
third_party/playwright-browsers/
third_party/runtime_manifest.json
workspace-ui/node_modules/
workspace-ui/.tmp-*.png
__pycache__/
.env
.adnify/
*_tmp*.png
```

## 新仓库建议 `.gitignore`

```gitignore
# Python
__pycache__/
*.py[cod]
.venv/

# Node
node_modules/
workspace-ui/node_modules/

# Local env/user state
.env
.adnify/

# User output
output/
*.wav
*.mp4

# Build artifacts
build/
dist/
dist-installer/

# Large runtime payloads
models/
third_party/chromium/
third_party/ffmpeg/
third_party/node/
third_party/node_runtime/
third_party/playwright-browsers/
third_party/downloads/
third_party/runtime_manifest.json
third_party/**/Release/
third_party/whisper.cpp/build-cuda/
third_party/whisper.cpp/build-core/

# Temporary screenshots / inspection files
*.tmp.png
_tmp_*.png
workspace-ui/.tmp-*.png
frame7_*.png
project_home*.png
start_page_after_button_swap.png
_inspect_main.txt
```

## 清理后必须验证

每次清理一批后运行：

```powershell
node --check workspace-ui/src/app.js
python -m compileall app.py src tests synpture_launcher.py
python -m unittest discover -s tests -p "test_*.py" -v
```

功能验收：

- `python app.py` 能启动。
- `/` 打开新前端首屏。
- 默认进入分享链接页。
- 顶部工具顺序不变：分享链接、本地媒体、文本输入、恢复项目。
- 系统设置能保存 `.env`。
- API key 保存后不消失。
- 健康自检能运行。
- 授权缺浏览器时给明确提示。
- 本地媒体转录前能做 GPU/CPU 能力判断。
- 没模型时给明确缺失原因，而不是硬崩。
- `output/` 历史项目和 `restored_projects/` 语义不变。

## 绝对不要碰坏的边界

- 不要把主工作台改回 Streamlit。
- 不要破坏 `python app.py`。
- 不要新增第二套前端栈。
- 不要改变默认首页和顶部工具顺序。
- 不要把中间 1200px 主热区改成别的布局原则。
- 不要破坏左右抽屉语义。
- 不要把授权检查改成假状态。
- 不要把主题偏好写进 `.env`。
- 不要破坏 `.env` 写回规则。
- 不要破坏 `output/` 与 `restored_projects/`。
- 不要把 GPU 转录链路静默改成 CPU-only。
- CPU 兜底必须是显式确认，不允许偷偷降级。

## 当前最值得做的清理优先级

1. 删除构建产物：`build/`、`dist/`、`dist-installer/`。
2. 删除运行输出：`output/`，如果需要保留历史项目先备份。
3. 删除临时截图和检查文件：根目录 `_tmp_*.png`、`frame7_*.png`、`project_home*.png`、`workspace-ui/.tmp-*.png`。
4. 删除缓存依赖：`workspace-ui/node_modules/`、`third_party/playwright-browsers/`。
5. 把大资源排除出新仓库：`models/`、`third_party/chromium/`、`third_party/ffmpeg/`、`third_party/node/`、`third_party/node_runtime/`、`third_party/whisper.cpp/`。
6. 单独开分支处理旧 Streamlit 代码，删除前先跑测试，删除后再跑测试。
