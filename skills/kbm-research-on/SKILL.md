---
name: kbm-research-on
description: 基于现有 KBManager knowledgebase、scope 和 outline 生成 ChatGPT Deep Research prompt 或 research brief。只读使用，不写入对象或调用 write API。
---

# KBManager Research On 工作流

使用此 skill 时，必须明确告诉用户：`Using skill: kbm-research-on`。

从现有 KBManager knowledgebase 生成 ChatGPT Deep Research prompt。

普通用户 workflow 中，不得修改 plugin 提供的 `SKILL.md`、`references/`、
`system-prompts/`、`src/kbmanager/`、`scripts/kbmanager_plugin.py` 或其他版本化资源。
只有用户明确要求进行 plugin 开发或维护时，才允许修改这些资源。

## 输入

- Knowledgebase ID；或
- `type: knowledge-base` object 的 Markdown 内容；或
- 用户当前明确指向的 knowledgebase。

## 规则

- 只读取目标 knowledgebase object、其 outlines YAML，以及识别它所需的最小上下文。
- 使用 knowledgebase 的 `description`、`scope` 和 outline 作为研究边界。
- 不要写入 KBManager object files。
- 不要调用 KBManager write APIs。
- 不要把派生索引当作事实；索引只能帮助定位 object。
- 不要包含与所选 knowledgebase 无关的私有 workspace 内容。
- 不要把 prompt 输出保存为 note、source、candidate 或 knowledge，除非用户另行发起对应 workflow。

## 输出

只返回 Deep Research prompt。该 prompt 必须要求：

- 从 knowledgebase description 推导研究目标；
- 从 `scope.includes` 和 `scope.excludes` 推导纳入和排除边界；
- 从 outline 推导报告结构；
- 对 factual claims 提供 citations；
- 在研究报告末尾列出使用过的 sources。
