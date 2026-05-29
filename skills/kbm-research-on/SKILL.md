---
name: kbm-research-on
description: 基于用户研究意图、现有 KBManager knowledgebase、scope 和 outline 生成 ChatGPT Deep Research prompt 或 research brief。只读使用，不写入对象或调用 write API。
---

# KBManager Research On 工作流

使用此 skill 时，必须明确告诉用户：`Using skill: kbm-research-on`。

从用户研究意图和现有 KBManager knowledgebase 生成 ChatGPT Deep Research prompt。

普通用户 workflow 中，不得修改 plugin 提供的 `SKILL.md`、`references/`、
`system-prompts/`、`src/kbmanager/`、`scripts/kbmanager_plugin.py` 或其他版本化资源。
只有用户明确要求进行 plugin 开发或维护时，才允许修改这些资源。

## 输入

- 用户研究意图或问题；以及
- Knowledgebase ID；或
- `type: knowledge-base` object 的 Markdown 内容；或
- 用户当前明确指向的 knowledgebase。

## 规则

- 先读取目标 knowledgebase object、其 outlines YAML，以及识别它所需的最小上下文。
- 使用 knowledgebase 的 `description`、`scope` 和 outline 作为研究边界。
- 根据用户研究意图判断当前已知内容、研究缺口，以及是否需要补充读取相关 knowledge/source；只读取为生成 prompt 所必需的对象。
- 不要写入 KBManager object files。
- 不要调用 KBManager write APIs。
- 不要把派生索引当作事实；索引只能帮助定位 object。
- 不要包含与所选 knowledgebase 无关的私有 workspace 内容。
- 不要把 prompt 输出保存为 note、source、candidate 或 knowledge，除非用户另行发起对应 workflow。

## 输出

只返回 Deep Research prompt。该 prompt 必须包含但不限于：

- 要研究的问题或用户意图；
- 已知内容、已有线索和当前研究状态；
- 研究方向、重点、优先级和排除项；
- knowledgebase `scope.includes`、`scope.excludes` 和 outline 推导出的边界；
- 要求 agent 在限定范围内充分、正确地研究，并输出结构化报告。

该 prompt 必须要求最终报告包含：

- 概述；
- 问题阐述；
- 研究原则、方向、scope 和重点；
- 按 outline 或研究逻辑组织的结构化正文；
- factual claims 的 citations；
- 报告末尾列出明文可复制的引用资源链接，并标记每个重点引用及使用理由。
