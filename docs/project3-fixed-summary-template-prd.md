# 工程3：首轮标准底稿 + 二轮固定模板 PRD

## 目标

把当前“转录后直接出一份 summary”的流程，升级为两层：

1. 首轮固定处理：先产出可读、可判断、可继续加工的标准底稿。
2. 二轮固定模板：基于首轮底稿，手动选择模板继续加工。

## 首轮结果页

首轮固定输出：

- 整理稿
- 一句话结论
- 价值判断
- 干货提取
- 补充理解（客观）
- 低价值内容标注
- 原始转录对照

页面结构：

1. `整理稿`
2. `结构化判断`
3. `原始转录对照`

## 二轮固定模板

- 学习精读 `study-deep-dive`
- 极简摘要 `minimal-summary`
- 行动提炼 `action-extraction`
- 课程笔记 `course-notes`
- 专业点评 `expert-review`

## 运行时模板目录

模板目录放在 `templates/skills/<template-id>/`，每个模板目录包含：

- `SKILL.md`
- `agents/openai.yaml`
- `template.json`

其中 `template.json` 是运行时唯一机器可读源。

## 恢复逻辑

- 只有 `transcript.txt + chunks.json`：恢复首轮
- 已有 `first_pass.json`：直接加载首轮结果
- 已有部分 `template_*.json`：允许继续生成其他模板

## 第一版约束

- 不自动执行任何二轮模板
- 首轮和二轮共用同一个模型选择器
- 不做用户自定义模板
- 不做服务端迁移
