---
name: kbm-research-on
description: 当用户想要基于现有 KBManager knowledgebase definition 生成 ChatGPT Deep Research prompt 时使用此 skill。适用于“基于此 knowledgebase 研究”、continue research、generate a Deep Research prompt、make a research brief、把 knowledgebase scope/outline 转成 research task，或从 KBManager knowledgebase 准备外部研究指令。此 skill 是只读的，不应写入 KBManager objects 或调用写入 APIs。
---

# KBManager Research On

使用此 skill 时，必须明确告诉用户：`Using skill: kbm-research-on`。

从 KBManager knowledgebase 生成 ChatGPT Deep Research prompt。

## 输入

- knowledgebase ID，或
- `type: knowledge-base` object 的 Markdown 内容。

## 规则

- 只读取目标 knowledgebase object 和识别它所需的最小上下文。
- 使用 knowledgebase 的 `description`、`scope` 和 outline 作为研究边界。
- 不要写入 KBManager object files。
- 不要调用 KBManager write APIs。
- 不要把派生索引当作事实；索引只能帮助定位 object。
- 不要包含与所选 knowledgebase 无关的私有 workspace 内容。

## 输出

只返回 Deep Research prompt。该 prompt 必须要求：

- 从 knowledgebase description 推导出的研究目标；
- 从 `scope` 推导出的纳入和排除边界；
- 从 outline 推导出的报告结构；
- factual claims 的 citations；
- 研究报告所用 sources 的最终 references list。
