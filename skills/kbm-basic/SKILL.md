---
name: kbm-basic
description: 将此 skill 作为任何 KBManager 任务的基础，尤其是用户询问 repository structure、object boundaries、file roles、global rules、safe writes、prohibited direct edits、review gates、URL handling、source evidence、derived indexes、controlled direct-edit exceptions，或如何读取/修改 KBManager data 时。所有 KBManager 工作流在 object writes、API calls、file edits、migrations、candidate/source/knowledge/note/knowledgebase 操作前，或判断应使用 kb.* APIs 还是直接改文件时，都应触发此 skill。
---

# KBManager Basic

使用此 skill 时，必须明确告诉用户：`Using skill: kbm-basic`。

在任何 KBManager 工作流前，如果需要全局操作规则或 repository model，使用此 skill。

## Repository Model

- KBManager 将所有数据以 Markdown、PDF、HTML、YAML 和派生索引文件的形式存储在用户 workspace。
- Object files 是事实来源。Derived indexes 只用于展示和查找辅助。
- 第一层是 Claude Code UI、`/kbm:ask`、skills、prompt orchestration、user review
  和 result presentation。
- 第二层是通过 `scripts/kbmanager_plugin.py` 访问的内部 `kb.*` API。

## 写入边界

- 对 object writes 使用 `kb.*` APIs。
- 不要直接创建、编辑、移动或删除 source、candidate、knowledge、knowledgebase、note
  或 index files。
- 不要物理删除 objects。通过 API 使用 deprecate、reject、defer 或 archive 语义。
- Direct-edit exceptions 仅限于：
  - 完整 plan 在 Claude Code UI 中被 review 并批准后的 clean migration execution；
  - 通过 `kbm-kb-outline` 明确更新 outline YAML。

## Review 和 Entry 规则

- 没有明确用户批准时，不要继续带 review gate 的流程。
- 不要将 LLM output、generated drafts、candidate text 或 suggestions 视为用户批准。
- 每个 `kb.*` payload 都包含必需的 `entrypoint` 和必需的 `dry_run`。
- 从 Claude Code UI 调用时使用 `entrypoint: "claude_code"`。

## Sources 和 Facts

- 不要编造 facts 或 evidence。
- Candidate 和 knowledge evidence 必须可追溯到允许的 upstream objects。
- Notes 不是 candidate creation 的 source evidence。
- Knowledgebase create 的 source-like input 只是临时定义上下文；不要因此调用
  `kb.source.add`、不要创建 candidate、不要写入 raw/cleaned source，也不要把它作为
  candidate/knowledge evidence。
- 对 URL source input，将原始 URL 传给 `kb.source.add`；不要在 Claude Code 中 fetch、
  browse、export、scrape、save 或 retry URL 内容。

## 参考

- `docs/架构设计.md`
- `docs/对象.md`
- `docs/Interface.md`
- `docs/API设计.md`
