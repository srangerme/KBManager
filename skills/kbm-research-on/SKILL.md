---
name: kbm-research-on
description: 当用户想要基于现有 KBManager knowledgebase/KB definition/scope/outline 生成 ChatGPT Deep Research prompt、research prompt、research brief、研究任务、继续研究、外部调研指令，或说“基于这个知识库研究”“continue research”“generate Deep Research prompt”“make a research brief”“把 KB scope/outline 转成研究计划”时使用此 skill。此 skill 只读读取 knowledgebase，不写入 KBManager objects，不调用 write APIs。
---

# KBManager Research On

使用此 skill 时，必须明确告诉用户：`Using skill: kbm-research-on`。

从现有 KBManager knowledgebase 生成 ChatGPT Deep Research prompt。

## Inputs

- Knowledgebase ID；或
- `type: knowledge-base` object 的 Markdown 内容；或
- 用户当前明确指向的 knowledgebase。

## Rules

- 只读取目标 knowledgebase object、其 outlines YAML，以及识别它所需的最小上下文。
- 使用 knowledgebase 的 `description`、`scope` 和 outline 作为研究边界。
- 不要写入 KBManager object files。
- 不要调用 KBManager write APIs。
- 不要把派生索引当作事实；索引只能帮助定位 object。
- 不要包含与所选 knowledgebase 无关的私有 workspace 内容。
- 不要把 prompt 输出保存为 note、source、candidate 或 knowledge，除非用户另行发起对应 workflow。

## Output

只返回 Deep Research prompt。该 prompt 必须要求：

- 从 knowledgebase description 推导研究目标；
- 从 `scope.includes` 和 `scope.excludes` 推导纳入和排除边界；
- 从 outline 推导报告结构；
- 对 factual claims 提供 citations；
- 在研究报告末尾列出使用过的 sources。
