# Synpture 工作台交接文档

## 1. 当前形态

当前项目已经从旧的 Streamlit 工作台切换为：

- Python 单进程启动
- `FastAPI` 提供正式 API 与静态资源
- `workspace-ui/` 作为首屏之后的正式前端工作台

主入口：

- [app.py](/C:/Users/59283/Desktop/MP4/app.py)
- [src/presentation/web_app.py](/C:/Users/59283/Desktop/MP4/src/presentation/web_app.py)
- [workspace-ui/src/app.js](/C:/Users/59283/Desktop/MP4/workspace-ui/src/app.js)
- [workspace-ui/src/styles.css](/C:/Users/59283/Desktop/MP4/workspace-ui/src/styles.css)

默认启动命令：

```powershell
python app.py
```

默认访问地址：

- `http://127.0.0.1:8000`

说明：

- 如果 `8000` 被占用，`app.py` 会自动顺延到下一个空闲端口
- 启动日志会打印最终实际地址

## 2. 前后端结构

### 后端

- `FastAPI` 负责：
  - `/` 前端入口
  - `/api/*` 工作台业务接口
  - `workspace-ui/` 静态资源
  - `assets/` 共享资源
- 核心桥接位于 [src/presentation/web_app.py](/C:/Users/59283/Desktop/MP4/src/presentation/web_app.py)

### 前端

- 前端是原生 `HTML + CSS + ESM JavaScript`
- 无 React、无打包器、无 Vite
- 主前端逻辑在 [workspace-ui/src/app.js](/C:/Users/59283/Desktop/MP4/workspace-ui/src/app.js)
- 主样式系统在 [workspace-ui/src/styles.css](/C:/Users/59283/Desktop/MP4/workspace-ui/src/styles.css)

### 状态模型

前端核心状态：

- `activeToolView`
- `selectedHistoryRunId`
- `leftDrawerOpen`
- `rightDrawerMode`
- `progressDetailsOpen`
- `activeTaskId`
- `activeTaskStatus`
- `activeTemplateId`
- `templatePanelTab`
- `selectedTemplateRecordId`

行为规则：

- 顶部工具态和历史项目态是分离的
- 选中历史项目后，顶部工具 active 清空
- 左项目列表可独立开合
- 右侧健康自检与系统设置互斥
- 执行任务时，大部分危险操作会被锁定

## 3. 已完成能力

### 首屏

- 首屏已迁入新前端，不再走 Streamlit 渲染
- 点击任意区域进入工作台
- Logo 使用本地资源：
  - [workspace-ui/assets/icons/Frame_11.svg](/C:/Users/59283/Desktop/MP4/workspace-ui/assets/icons/Frame_11.svg)
- Aurora 背景已接入本地 `ogl` 运行时

### 工具页

已接通以下正式工具页：

- `分享链接`
- `本地媒体`
- `文本输入`
- `恢复项目`

默认首页：

- `分享链接`

顶部顺序：

- `分享链接 / 本地媒体 / 文本输入 / 恢复项目`

### 历史项目

- 历史项目列表从真实本地 `output/` 读取
- 选中项目后，中间 1200 区切到项目工作区态
- 目前项目列表展示：
  - 标题
  - 本地路径
  - 时间
  - 状态
  - 进度

### 处理链路

当前已经接通真实链路：

- 分享链接创建任务
- 本地媒体上传任务
- 文本文件任务
- 粘贴文本任务
- 恢复目录任务
- `transcript_only -> 第一稿`
- 模板二次深化
- 下载产物
- 健康自检
- 系统设置读取与保存
- 抖音 / B 站授权打开与状态检查

### 任务执行模型

- 前端发起任务后，后端返回 `task_id`
- 前端轮询 `/api/tasks/{task_id}/status`
- 成功后刷新 bootstrap / 项目详情
- 当前采用轮询，不是 SSE / WebSocket

任务注册表：

- [src/presentation/task_registry.py](/C:/Users/59283/Desktop/MP4/src/presentation/task_registry.py)

## 4. API 概览

当前正式使用的主要接口：

- `GET /api/bootstrap`
- `GET /api/runs`
- `GET /api/runs/{run_id}`
- `GET /api/runs/{run_id}/download/{artifact_name}`
- `POST /api/tasks/share-link`
- `POST /api/tasks/local-media`
- `POST /api/tasks/text-file`
- `POST /api/tasks/pasted-text`
- `POST /api/tasks/recovery/uploaded-dir`
- `POST /api/runs/{run_id}/resume-first-pass`
- `POST /api/runs/{run_id}/templates/{template_id}`
- `GET /api/tasks/{task_id}/status`
- `POST /api/tasks/{task_id}/cancel`
- `GET /api/health`
- `POST /api/health/run`
- `GET /api/settings`
- `POST /api/settings`
- `POST /api/settings/test-connection`
- `GET /api/settings/models`
- `POST /api/settings/test-model`
- `POST /api/auth/{platform}/open`
- `GET /api/auth/{platform}/status`

序列化映射集中在：

- [src/presentation/api_serializers.py](/C:/Users/59283/Desktop/MP4/src/presentation/api_serializers.py)

## 5. 第一稿与模板深化的当前定义

### 第一稿

当前中间工作区“第一稿”定义：

- 目标是把原始转录整理成可读初稿
- 标题由模型自动改名
- 一句话副标题表达“值不值得看”
- 正文按段落输出
- 段落按价值等级着色
- 右侧原稿抽屉默认收起，展开后可对照时间轴转录稿

目前支持的价值等级：

- `高价值`
- `值得看`
- `普通`
- `不值得`

辅助区块：

- `高价值信息`
- `客观背景`

### 模板深化

模板深化目前分两层：

- 模板列表
- 生成记录

模板卡能力：

- 未生成时可开始生成
- 已生成时可查看记录
- 已生成时可重复生成
- 某模板在生成时，其它模板生成按钮会锁定

生成记录能力：

- 左侧是记录列表
- 右侧是阅读详情

## 6. 当前视觉规范

### 布局基线

- 1920 设计基准
- 中间主热区固定 `1200px`
- 左右轨道对称
- 顶栏 / 左抽屉 / 右抽屉 共用同一对齐基线

### 主要 spacing token

只允许使用：

- `6, 8, 10, 12, 14, 16, 18, 20, 24, 28, 32, 40`

### radius token

- `14 / 16 / 20 / 24 / 28 / pill`

### 当前收口重点

近期已经重点收过：

- 第一稿区
- 模板深化区
- 行高统一
- 按钮内边距统一
- 图标按钮尺寸统一

### 仍需注意

- 样式文件较大，历史覆盖较多
- 新功能尽量继续追加“末尾高优先级统一规则”，不要在中部到处插零散覆盖
- 新增视觉组件优先复用已有 token，不要再自由造数值

## 7. 动效与图标来源

### Aurora 背景

首屏背景参考来源：

- [Soft Aurora - ReactBits](https://reactbits.dev/backgrounds/soft-aurora)

当前实际实现说明：

- 没有直接引 React 组件
- 参考其 OGL shader 思路，改写为原生 JS 版本
- 为避免运行时依赖 `node_modules` 静态路径失效，已将 `ogl` 运行时代码内置到：
  - [workspace-ui/vendor/ogl/](/C:/Users/59283/Desktop/MP4/workspace-ui/vendor/ogl)

### 图标

当前图标资源为本地 SVG：

- [workspace-ui/assets/icons/](/C:/Users/59283/Desktop/MP4/workspace-ui/assets/icons)

包含：

- `activity.svg`
- `settings.svg`
- `refresh.svg`
- `close.svg`
- `Frame_11.svg`

图标设计参考来源：

- [Iconoir](https://github.com/iconoir-icons/iconoir)

说明：

- 当前项目没有把整套 Iconoir 作为运行时依赖引入
- 采用的是本地精简 SVG 资源 + CSS mask 渲染方案

## 8. 依赖说明

### Python

主要运行依赖写在：

- [requirements.txt](/C:/Users/59283/Desktop/MP4/requirements.txt)

### 前端

前端只有一个额外 npm 依赖记录：

- `ogl`

位置：

- [workspace-ui/package.json](/C:/Users/59283/Desktop/MP4/workspace-ui/package.json)

说明：

- 当前前端不是 npm 构建型项目
- `workspace-ui/package.json` 的主要意义是记录 `ogl` 来源
- 实际运行时不依赖 `node_modules/ogl` 路径，而依赖 `workspace-ui/vendor/ogl/`

## 9. 测试与验收

### 前端基本检查

```powershell
node --check workspace-ui/src/app.js
```

### Python 回归

```powershell
python -m compileall app.py src tests
python -m unittest discover -s tests -p "test_*.py" -v
```

当前状态：

- 单测全绿
- 最近一次回归为 `55/55 OK`

## 10. 已知问题与接手建议

### 已知问题

- `workspace-ui/src/styles.css` 体量较大，仍有较多历史覆盖层
- 个别区域仍可能存在局部密度偏差，需要在真实验收时继续肉眼调整
- 小红书 / 微信蝴蝶号目前仍是占位 UI，不是正式接入

### 接手建议

下一位开发新功能时建议顺序：

1. 先看本文档
2. 再看 [README.md](/C:/Users/59283/Desktop/MP4/README.md)
3. 再看 [workspace-ui/src/app.js](/C:/Users/59283/Desktop/MP4/workspace-ui/src/app.js)
4. 最后再看 [workspace-ui/src/styles.css](/C:/Users/59283/Desktop/MP4/workspace-ui/src/styles.css)

新增功能时建议：

- 先补 `app.js` 结构
- 再在 `styles.css` 末尾补最终统一规则
- 不要先在中段到处打补丁
- 不要重新引回 Streamlit UI

## 11. 为什么文档拆成两份

建议保留两份文档：

- `README.md`
  - 只负责启动、入口、测试、总览
- `docs/workspace-handover.md`
  - 负责改造背景、前后端边界、状态模型、视觉规范、依赖来源、已知问题

原因：

- README 适合新人快速启动
- 交接文档适合下一位开发真正接手
- 如果把所有历史改造细节全塞进 README，后面会很难维护

## 12. 哪些能动，哪些不能动

这一节是给下一位开发者的硬边界。

### 12.1 可以直接改动的范围

在不改变产品主路径的前提下，可以直接开发和调整：

- [workspace-ui/src/app.js](/C:/Users/59283/Desktop/MP4/workspace-ui/src/app.js)
  - 新功能交互
  - 新的前端状态
  - 现有区块内部结构优化
  - API 调用接线
- [workspace-ui/src/styles.css](/C:/Users/59283/Desktop/MP4/workspace-ui/src/styles.css)
  - 新功能样式
  - 现有视觉收口
  - token 复用下的间距与排版修正
- [src/presentation/web_app.py](/C:/Users/59283/Desktop/MP4/src/presentation/web_app.py)
  - 新 API
  - 现有 API 扩展
  - 前端桥接逻辑
- [src/presentation/api_serializers.py](/C:/Users/59283/Desktop/MP4/src/presentation/api_serializers.py)
  - 前端所需字段扩充
  - 现有 payload 映射增强
- [src/presentation/task_registry.py](/C:/Users/59283/Desktop/MP4/src/presentation/task_registry.py)
  - 任务状态扩充
  - 任务并发 / 中止 / 轮询细节优化
- 业务层中与新功能直接相关的非 UI 能力
  - 例如模板、恢复、下载、授权检查、自检补充

### 12.2 不允许随意改动的范围

以下内容默认视为“冻结约束”，除非产品负责人明确同意，否则不要推翻：

- 不要把主工作台改回 Streamlit UI
- 不要新增第二套前端栈
  - 不要再起 React / Vue / Next 独立工程
- 不要破坏 `python app.py` 的单命令启动方式
- 不要移除 `FastAPI + workspace-ui` 这一主架构
- 不要把首屏重新改回旧的 `render_start_page_v2()` 运行时渲染
- 不要修改工具默认顺序
  - `分享链接 / 本地媒体 / 文本输入 / 恢复项目`
- 不要修改默认首页
  - 默认仍然是 `分享链接`
- 不要把中间主热区改成流动宽度
  - 中间主区仍以 `1200px` 为固定核心热区
- 不要把左右抽屉改回普通侧栏
  - 左侧是项目列表抽屉
  - 右侧是健康自检 / 系统设置抽屉
- 不要让右侧两个抽屉同时打开
- 不要让历史项目选中态重新影响顶部工具 active
- 不要删除真实授权检查逻辑
  - 抖音 / B站状态必须来自检查结果，不允许伪绿灯
- 不要破坏 `.env` 写回规则
  - 仅允许写回既定字段
  - 必须尽量保留注释、未知键、原顺序
- 不要随意改动产物目录与恢复语义
  - `output/` 下项目目录仍是恢复和历史项目的真实来源
- 不要把转录链路偷偷切回 CPU-only 方案
  - 当前目标仍是维持 `whisper.cpp` 的 GPU 路径可用

### 12.3 首屏属于高敏感区域

首屏可以微调，但不允许破坏这几个既定结论：

- 点击任意区域进入工作台
- 不要恢复“点击开始”按钮方案
- Logo 使用：
  - [workspace-ui/assets/icons/Frame_11.svg](/C:/Users/59283/Desktop/MP4/workspace-ui/assets/icons/Frame_11.svg)
- 背景维持 Aurora 方向
- 首屏资源缺失时不能因为 `node_modules` 静态路径导致整页空白
  - 当前 `ogl` 运行时已内置在：
  - [workspace-ui/vendor/ogl/](/C:/Users/59283/Desktop/MP4/workspace-ui/vendor/ogl)

## 13. 新功能开发必须遵守的回归规则

下一位开发者每做完一轮功能，至少要自检下面这些点：

### 13.1 启动与架构回归

- `python app.py` 仍能直接启动
- `/` 仍是新前端，不是旧 Streamlit 工作台
- 首屏正常显示
- 点击首屏可进入工作台

### 13.2 工作台结构回归

- 顶部顺序仍是：
  - `分享链接 / 本地媒体 / 文本输入 / 恢复项目`
- 默认首页仍是 `分享链接`
- 中间主热区仍固定 `1200px`
- 左项目列表抽屉可独立开合
- 右侧健康自检 / 系统设置仍互斥
- 页面仍然是单一纵向滚动
- 不要再造独立抽屉滚动条

### 13.3 任务与业务回归

- 分享链接任务可创建
- 本地媒体任务可创建
- 文本输入任务可创建
- 恢复项目任务可创建
- 第一稿可继续生成
- 模板二次深化可执行
- 模板生成时其它模板不能重复触发执行
- 下载仍可用
- 健康自检仍可运行
- 设置仍可保存
- 抖音 / B站授权检查仍是“真实检查”，不是假状态

### 13.4 视觉回归

- 不要随意新增 magic number
- 间距优先复用既有 token
- 新增区块优先接入统一标题 / 正文 / 按钮 / 标签节奏
- 不要再引入“框和字贴一起”的控件
- 图标按钮尺寸要与当前基线一致，不要再次缩回去

### 13.5 测试回归

至少执行：

```powershell
node --check workspace-ui/src/app.js
python -m compileall app.py src tests
python -m unittest discover -s tests -p "test_*.py" -v
```

## 14. 给下一位开发者的建议工作方式

建议开发顺序：

1. 先读 [README.md](/C:/Users/59283/Desktop/MP4/README.md)
2. 再读 [docs/workspace-handover.md](/C:/Users/59283/Desktop/MP4/docs/workspace-handover.md)
3. 先跑起 `python app.py`
4. 先在浏览器里过一遍当前页面，再开始写代码
5. 先改 [workspace-ui/src/app.js](/C:/Users/59283/Desktop/MP4/workspace-ui/src/app.js) 的结构与逻辑
6. 再在 [workspace-ui/src/styles.css](/C:/Users/59283/Desktop/MP4/workspace-ui/src/styles.css) 末尾补最终样式统一规则
7. 不要先在样式文件中部到处打散补丁

如果要加新功能，优先策略：

- 先保证能跑通真实数据
- 再收视觉
- 不要先把页面完全重画再找后端对接

## 15. 你可以直接转发给下一位的话

可以直接把下面这段原样发给下一位开发者：

“当前主工作台已经切到 `FastAPI + workspace-ui`，不要再回退到旧 Streamlit 工作台。  
你先看 `README.md` 和 `docs/workspace-handover.md`。  
能动的主要是 `workspace-ui/src/app.js`、`workspace-ui/src/styles.css`、`src/presentation/web_app.py`、`src/presentation/api_serializers.py`。  
不能动的是主架构、默认首页顺序、1200 主热区、左右抽屉语义、真实授权检查、`.env` 写回规则、恢复与产物目录语义。  
每次改完至少跑 `node --check`、`compileall`、`unittest`，并手动回归首屏、工具页、任务执行、模板深化、设置、自检和授权状态。” 
