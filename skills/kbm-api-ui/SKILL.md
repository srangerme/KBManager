---
name: kbm-api-ui
description: 当 Claude Code 需要通过 scripts/kbmanager_plugin.py 调用、校验、dry-run、resume 或解释 KBManager kb.* APIs 时使用此 skill。适用于 API payload 构造、entrypoint="claude_code"、dry_run 要求、needs_llm 处理、needs_review gates、带 review gate 的操作、result status 处理、operation IDs、warnings/errors，或关于哪些 KBManager APIs 可从 Claude Code UI 调用的问题。调用 kb.* 操作前，应与相关工作流 skill 配合使用。
---

# KBManager API UI

使用此 skill 时，必须明确告诉用户：`Using skill: kbm-api-ui`。

从 Claude Code UI 调用 `scripts/kbmanager_plugin.py` 前，或记录 UI 可调用的
KBManager 操作时，使用此 skill。

## 辅助脚本契约

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" <kb.operation> '<payload-json>' --pretty
```

- Payload 是 JSON object。
- Result 是内部 API result model 产生的 JSON object。
- 每个 payload 必须包含 `entrypoint: "claude_code"`。
- 每个 payload 必须包含 `dry_run`。在不执行写入、移动或 LLM resume 的情况下验证时，
  使用 `dry_run: true`。
- 如果 API 返回 `needs_llm`，使用其 `llm_request`，匹配其 schema，并用返回的 token
  恢复同一操作。
- 如果 API 返回 `needs_review`，在 Claude Code UI 中暂停，直到用户 approve、edit
  或 reject proposed action。

## UI 能力边界

只要遵守参数、review gates 和 dry-run 行为，Claude Code UI 可以调用所有已文档化的
`kb.*` 操作。

## 流程

```mermaid
flowchart TD
  A["Claude Code UI 请求"] --> B["选择工作流 skill"]
  B --> C["构造包含 entrypoint=claude_code 的 JSON payload"]
  C --> D{"dry_run?"}
  D -- yes --> E["仅验证并报告 plan/errors"]
  D -- no --> F["调用 kb.* helper"]
  F --> G{"API status"}
  G -- needs_llm --> H["生成匹配 schema 的 llm_result"]
  H --> I["恢复同一操作"]
  I --> G
  G -- needs_review --> J["在 Claude Code UI 中询问用户"]
  J --> K["调用已批准的 review-gated operation"]
  K --> G
  G -- success/failed/partial --> L["报告 IDs、warnings、errors、next actions"]
```

## 参考

- `references/api-ui-catalog.md`
- `references/api-ui-flowcharts.md`
- `docs/API设计.md`
- `docs/Interface.md`
