---
description: 理解 KBManager 请求并编排正确的 API 工作流
---

# KBManager Ask

将 `$ARGUMENTS` 作为用户的 KBManager 请求。这是唯一的 KBManager slash command。
理解用户意图，选择相关的 `kbm-*` skill，然后按需调用随附的内部 JSON helper。

## 必需 Skills

- 所有 KBManager 请求都先使用 `kbm-usage` 获取全局对象、写入、审核、来源、索引、API payload/result 和 helper 调用规则。
- 根据用户意图使用匹配领域 skill：
  `kbm-source`, `kbm-candidate`, `kbm-note`, `kbm-kb`, `kbm-maintenance`。
- 从 knowledgebase 生成 ChatGPT Deep Research prompt 时，使用 `kbm-research-on`。
- 所有 knowledgebase、KB、outline、default outline、outline YAML、section tree、taxonomy、map 或 KB 结构维护请求，都使用 `kbm-kb`。

## Intent Routing

- Source lifecycle：添加、导入、摄取、登记、废弃 source，PDF/Markdown/file/directory source，或从材料生成 pending candidates，使用 `kbm-source`。
- Candidate and knowledge review：创建 candidate、获取 candidate、下一个 pending、审核、accept/reject/defer/merge candidate、deprecate accepted knowledge、处理 evidence 或 bindto，使用 `kbm-candidate`。
- Notes：添加、记录、保存、生成标题、查看、列出、废弃 note，使用 `kbm-note`。
- Knowledgebase and outline：创建/列出/map knowledgebase，创建/set default/archive outline，维护 outline YAML nodes，修复 outline bindings，使用 `kbm-kb`。
- Maintenance：init、check、index rebuild、clean inspect、migration plan、clean migration execution，使用 `kbm-maintenance`。
- Research prompt：基于 existing knowledgebase scope/outline 生成外部研究 prompt，使用 `kbm-research-on`。

## Core Rules

- 执行任何 KBManager 操作前，必须先加载并阅读 `kbm-usage` 和匹配用户意图的领域 skill。
- 不要直接创建、编辑、移动或删除 KBManager object files。
- 对 object writes，必须通过 `scripts/kbmanager_plugin.py` 调用 `kb.*` APIs。
- Clean migration execution 只有在完整 migration plan 已展示在 Claude Code UI 且获得用户明确批准后，才可以直接编辑文件。
- 用户明确要求更新现有 outline YAML 时，`kbm-kb` 定义一个独立的受控直接编辑例外。
- 不要把派生索引当作事实；索引只用于定位、展示和一致性检查。
- 不要物理删除 source、note、candidate、knowledge 或 knowledgebase objects。使用 deprecate、reject、defer 或 archive 语义。
- 如果 API 返回 `needs_llm`，生成 API 请求的结构化输出，并使用同一个 `resume_token` 恢复同一操作。
- 如果 API 返回 `needs_review`，在 Claude Code UI 中暂停并收集明确的用户决定，然后再调用写入 API。
- 创建 knowledgebase 时用户提供的 source/file/directory 只是 source-like context；不要调用 `kb.source.add`，不要创建 candidate，也不要把该 input 写成 evidence。

## Helper Invocation

对 `kb.*` 操作调用内部 JSON helper：

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" <kb.operation> '<payload-json>' --pretty
```


读取 JSON result 并报告 `status`、`operation`、created/updated/deprecated objects、
diffs、warnings、errors、review options、returned IDs 和 next actions。

## Standard Workflow

1. 将用户请求解析为意图、必需输入和可能的领域工作流。
2. 加载并阅读 `kbm-usage` 和匹配的领域 skill。
3. 如果缺少必需输入，在 Claude Code UI 中询问。
4. 只执行所选领域工作流允许的 API 调用。
5. 使用 API 返回的结构化请求和 resume token 处理 `needs_llm`。
6. 在任何写入 API 继续前，在 Claude Code UI 中处理 `needs_review`。
7. 总结最终结果，包括 created、updated、deprecated、rejected 或 deferred 的 object IDs，以及 warnings、errors 和 next actions。
