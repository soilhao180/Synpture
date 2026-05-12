# Synpture 交接文档

## 当前交接状态

当前无进行中交接；请以 `README.md` + `PROJECT_MAP.md` 为准。

`README.md` 负责源码版/安装版如何运行、配置、恢复资源和打包。  
`PROJECT_MAP.md` 负责稳定代码地图、模块入口、开发规范、测试命令和硬边界。

## 下一次大版本交接模板

大版本分支合并并跑通后，在本节下方新增一段；不要把流水账写入 `PROJECT_MAP.md`。

```markdown
## YYYY-MM-DD：<版本/分支/主题>

### 合并状态
- 分支：
- 合并到：
- 验证结果：
- 安装包/资源包：

### 本轮主要变化
- 

### 关键文件
- 

### 风险和硬边界
- 

### 下一步建议
- 
```

## 历史阶段记录

### 2026-05-12：开发运行时资源与 env 写回修复

最近主要修了三类问题：

1. Lite 安装包资源下载逻辑误伤本地开发模式，导致 `python app.py` 启动后点转录没反应。
2. 前端保存 API key 后 `.env` 被写坏，出现裸露的多行 `sk-...`。
3. 本地 `python app.py` 按 `Ctrl+C` 退出时 PowerShell 打出 `CancelledError / KeyboardInterrupt` traceback，看起来像崩溃。

#### 当前已修改文件

这些改动是有意的，已经用于修复上述问题：

- `app.py`
- `src/presentation/config_io.py`
- `src/presentation/web_app.py`
- `src/runtime_resources.py`
- `tests/test_workspace_refactor.py`
- `workspace-ui/src/app.js`
- `tests/test_runtime_resources.py`
- `HANDOFF.md`

#### 修复 1：本地 `python app.py` 点转录没反应

##### 根因

Lite 资源系统新增后，前端提交转录前会检查：

- `model`
- `transcription_runtime`

但本地开发模式资源实际在源码旧路径：

- `models/ggml-large-v3-turbo-q5_0.bin`
- `third_party/ffmpeg/bin/ffmpeg.exe`
- `third_party/ffmpeg/bin/ffprobe.exe`
- `third_party/whisper.cpp/build-cuda/bin/whisper-cli.exe`
- `third_party/whisper.cpp/build-core/bin/whisper-cli.exe`
- `third_party/node/node.exe`
- `third_party/node_runtime/node_modules/playwright/package.json`
- `third_party/chromium/chrome.exe`

新资源检查只认 Lite 安装版下载目录：

- `third_party/transcription_runtime/...`
- `third_party/browser_runtime/...`

所以本地资源被误判为 missing，前端按钮在提交前被资源门禁拦住，看起来像“点了没反应”。

##### 已改内容

文件：`src/runtime_resources.py`

- 新增开发模式源码资源 fallback。
- 只有在“非 packaged 且 user data root 等于 app root”时才启用 fallback。
- 安装版仍然只认 `%AppData%\Synpture` / Lite 下载资源，不偷用源码路径。
- `serialize_runtime_resource()` 的 `targetPath` 会显示当前真正生效路径。

文件：`tests/test_runtime_resources.py`

- 新增测试覆盖开发模式源码资源 ready。
- 新增测试覆盖 packaged 模式不使用开发 fallback。

##### 当前本地资源状态

已验证当前本地开发模式下：

- `model`: ready
- `browser_runtime`: ready
- `transcription_runtime`: ready

#### 修复 2：前端保存 API key 写坏 `.env`

##### 根因

`src/presentation/config_io.py` 原来的正则是：

```python
r"^(\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*=\s*)(.*?)(\r?\n)?$"
```

其中 `\s*=\s*` 会吃掉换行。

当 `.env` 中存在空的 API key 配置行，再保存密钥时，可能写成多行，导致 `.env` 中出现裸露的 orphan secret 行。

##### 已改内容

文件：`src/presentation/config_io.py`

- 正则改成不吃换行：

```python
r"^([^\S\r\n]*)([A-Za-z_][A-Za-z0-9_]*)([^\S\r\n]*=[^\S\r\n]*)([^\r\n]*)(\r?\n)?$"
```

- 保存值前统一 `strip()`。
- 如果 value 包含 `\r` 或 `\n`，直接抛 `ValueError`。
- 写回 `.env` 时自动删除疑似裸 API key 行：`sk-...`。

文件：`src/presentation/web_app.py`

- 保存设置时捕获 `ValueError`，返回 HTTP 400，避免 500。

文件：`workspace-ui/src/app.js`

- 设置输入框增加 `normalizeSettingInput()`。
- `summaryApiKey` 如果混入多行，只取第一段非空内容。
- 其它设置项把换行替换为空格并 `trim()`。

文件：`tests/test_workspace_refactor.py`

- 新增测试：清理 orphan API key 行。
- 新增测试：拒绝多行 API key。

##### 当前 `.env` 状态

用户本地 `.env` 已清理。不要在文档或提交里写入真实 API key。用户可以重新在前端系统设置里保存 API key。

##### 建议验证流程

```powershell
python app.py
```

然后在前端：

1. 系统设置里重新粘贴 API key。
2. 点保存。
3. 点测试连接 / 获取模型 / 测试模型。
4. 检查 `.env` 是否只写成一行 API key 配置，不出现裸露 orphan secret 行。

如果还复发，优先检查：

- 浏览器自动填充是否把多行值填入输入框。
- `workspace-ui/src/app.js` 的 `normalizeSettingInput()` 是否生效。
- 保存接口收到的 payload 是否含换行。

#### 修复 3：`Ctrl+C` 退出时 traceback

##### 现象

用户截图中前面已经正常显示：

```text
Application shutdown complete.
Finished server process
```

后面又打印：

- `asyncio.exceptions.CancelledError`
- `KeyboardInterrupt`

##### 判断

这是 Windows PowerShell 下 `Ctrl+C` 结束 `uvicorn.Server.run()` 时的正常取消信号，被 Python runner 打成 traceback，不是业务崩溃。

##### 已改内容

文件：`app.py`

增加：

```python
import asyncio
```

并包住 `server.run()`：

```python
try:
    create_uvicorn_server(create_web_app(), host=host, port=port).run()
except (KeyboardInterrupt, asyncio.CancelledError):
    pass
```

目标：`python app.py` 按 `Ctrl+C` 后不再喷正常退出 traceback。

#### Lite 安装包与资源系统背景

之前已经做过 Lite 安装包方向：

- 默认安装包输出目录：`Synpture/`
- Lite 包思路：
  - 安装器不内置模型、浏览器 runtime、转录 runtime。
  - 首次使用从 GitHub Releases 下载。

资源 manifest：

- `packaging/runtime_resources.json`

资源 API：

- `GET /api/runtime/resources`
- `POST /api/runtime/resources/{resource_id}/download`
- `GET /api/runtime/resources/{resource_id}/status`
- `POST /api/runtime/resources/{resource_id}/upload`

资源 id：

- `model`
- `browser_runtime`
- `transcription_runtime`

Release 附件：

- `synpture-model-ggml-large-v3-turbo-q5_0.bin`
- `synpture-browser-runtime-win-x64.zip`
- `synpture-transcription-runtime-win-x64.zip`
- `SHA256SUMS.txt`

SHA256：

- model:
  `394221709cd5ad1f40c46e6031ca61bce88931e6e088c188294c6d5a55ffa7e2`
- browser_runtime:
  `ead7b06190634c61fe46b8223c2df2f4c3bade7c385ffdd5c6b33413499cd477`
- transcription_runtime:
  `8da3c68a8c57699b0317d5c31003713e909c39d862d845da1b75a660203ea5c6`

注意：

- `packaging/runtime_resources.json` 在终端里可能显示乱码，但 JSON 可读。
- 不要随便改下载 URL 或 SHA，除非明确要重打资源包。

#### Git 背景

当前仓库远端：

```text
origin git@github.com:soilhao180/Synpture.git
```

当前分支：

```text
main
```

继续前先确认：

```powershell
git status --short
git remote -v
git branch --show-current
```

#### 必跑命令

每次改完至少跑：

```powershell
node --check workspace-ui/src/app.js
python -m compileall app.py src tests synpture_launcher.py
python -m unittest discover -s tests -p "test_*.py" -v
```

最近一次完整回归已通过：

```text
Ran 105 tests ... OK
```

#### 用户偏好与协作方式

- 用户希望直接、实用，不要绕。
- 用户很关注“是不是又凭感觉改”。
- 改代码前要说明根因与具体改动方向。
- 对 UI/样式问题要先出规范/排查计划，再实施。
- 对安装包/运行环境问题要明确区分：
  - 开发模式。
  - 安装版。
  - 哪些资源必须存在。
  - 哪些可下载。
  - 哪些不能假状态。
- 避免大而泛的回答，优先给能执行的命令和文件路径。

#### 下一步建议

1. 先确认用户是否要验证本地启动：

```powershell
python app.py
```

2. 让用户在前端重新保存 API key，并测试连接。
3. 测试本地媒体/分享链接转录入口是否能正常提交。
4. 按 `Ctrl+C` 退出，观察是否还打印 traceback。
5. 如果继续安装包方向，再重新构建 Lite 包并在新电脑验证。
