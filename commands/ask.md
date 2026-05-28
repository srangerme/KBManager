---
description: 理解 KBManager 请求并编排正确的 API 工作流
---

# KBManager Ask

将 `$ARGUMENTS` 作为用户的 KBManager 请求。这是唯一的 KBManager
slash command。理解用户意图，选择相关的 `kbm-*` skill，然后按需调用随附的辅助脚本。

## 必需 Skills

- 使用 `kbm-basic` 处理全局写入、审核、来源、URL、索引和删除规则。
- 从 Claude Code UI 调用 `scripts/kbmanager_plugin.py` 前，或解释 UI 可调用 API payload 前，
  使用 `kbm-api-ui`。
- 根据用户意图使用匹配的工作流 skill：
  `kbm-source`, `kbm-candidate`, `kbm-note`,
  `kbm-kb`, `kbm-kb-outline` 或
  `kbm-maintenance`.
- 从 knowledgebase 生成 Deep Research prompt 时，使用 `kbm-research-on`。
- 只有在用户明确要求直接更新 outline YAML 时，才使用
  `kbm-kb-outline` 的 outline 更新章节。

## 核心规则

- 执行任何 KBManager 操作前，必须先加载并阅读 `kbm-basic`、`kbm-api-ui`
  和匹配用户意图的工作流 skill。不要跳过 skill 阅读。
- 不要直接创建、编辑、移动或删除 KBManager object 文件。
- 对 object 写入，必须通过 `scripts/kbmanager_plugin.py` 使用 `kb.*` APIs。
- 特权 clean migration 路径只有在完整 migration plan 已展示在 Claude Code UI
  且获得用户明确批准后，才可以直接编辑文件。
- 通过 `kbm-kb-outline` 明确更新 outline YAML 是独立的受控直接编辑例外。
- 不要把派生索引当作事实。
- 不要物理删除 source、note、candidate、knowledge 或 knowledgebase objects。
- 如果 API 返回 `needs_llm`，生成符合其返回 schema 的输出，并使用相同的
  `resume_token` 恢复同一操作。
- 如果 API 返回 `needs_review`，在 Claude Code UI 中暂停并收集明确的用户决定，
  然后再调用写入 API。
- 对 URL source 输入，不要在 Claude Code 中 fetch、browse、export、scrape、save
  或 retry 该 URL。将原始 URL 传给 `kb.source.add`。
- 创建 knowledgebase 时用户提供的 source/file/URL 只是 source-like context；
  不要调用 `kb.source.add`，不要创建 candidate，也不要把该 input 写成 evidence。

## 辅助脚本调用

对 `kb.*` 操作调用内部 JSON 辅助脚本：

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" <kb.operation> '<payload-json>' --pretty
```

Payload 必须是 JSON object。读取 JSON 结果并报告 status、object IDs、warnings、
errors、diffs 和下一步操作。

每个 `kb.*` API payload 都必须包含 `entrypoint` 和 `dry_run`。从 Claude Code UI
调用时使用 `entrypoint: "claude_code"`。验证请求且不执行写入、文件移动或 LLM
恢复时，设置 `dry_run: true`。

## 意图工作流

1. 将用户请求解析为意图、必需输入和可能的工作流。
2. 执行任何操作前，加载并阅读 `kbm-basic`、`kbm-api-ui` 和匹配的工作流 skill。
3. 如果缺少必需输入，在 Claude Code UI 中询问。
4. 只执行所选工作流允许的 API 调用。
5. 使用 API 提供的 prompt/schema 和 resume token 处理 `needs_llm`。
6. 在任何写入 API 继续前，在 Claude Code UI 中处理 `needs_review`。
7. 总结最终结果，包括 created、updated、deprecated、rejected 或 deferred 的
   object IDs，以及任何返回的 warnings 或 errors。
