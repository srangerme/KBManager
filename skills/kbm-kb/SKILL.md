---
name: kbm-kb
description: 当用户要求创建 knowledgebase、定义 knowledgebase scope、列出 knowledgebases、map knowledgebase、检查可用 knowledgebases，或从 source-like input 生成包含 title、description、tags、scope 和 default outline 的 reviewed knowledgebase draft 时使用此 skill。适用于 knowledgebase create/list/map、KB definition、domain scope、knowledgebase catalog、knowledge map，以及已批准创建新的 KBManager knowledgebase objects。创建 knowledgebase 时提供的 source/file/URL 只是临时上下文，不触发 source add 或 candidate create。outline 生命周期或 YAML node edits 使用 outline-specific skill。
---

# KBManager Knowledgebase Workflows

使用此 skill 时，必须明确告诉用户：`Using skill: kbm-kb`。

## Knowledgebase Create

1. 收集 title 和 source-like context。
2. 临时读取或采集该 context，仅用于 `knowledgebase-create.md` draft generation。
3. 使用内部 prompt module 生成 knowledgebase draft。
4. 在 Claude Code UI 中展示 description、tags、scope、default outline 和 outlines。
5. 收集明确批准或编辑后的 reviewed content。
6. 调用 `kb.knowledgebase.create`。

Knowledgebase create 需要 review gate。

创建 knowledgebase 时，用户给出的 source、file、directory 或 URL 不等于
KBManager source lifecycle input。此工作流不得调用 `kb.source.add`，不得调用
`kb.candidate.create`，不得写入 `data/raw` 或 `data/cleaned`，也不得把该 input
记录为 candidate/knowledge evidence。`kb.knowledgebase.create` 只接收 review 后的
knowledgebase payload，并只创建 active knowledgebase Markdown 和 outlines YAML。

## Knowledgebase List

- 读取 derived indexes 或 object files 仅用于展示。
- 不要将 index text 视为 factual evidence。
- 可见时标记 deprecated 或 archived 状态。

## Knowledgebase Map

- 调用 `kb.knowledgebase.map`。
- 没有 review gate。
