# `kb.knowledgebase.create`

## 用途

创建 active knowledgebase 和配套 outlines YAML。输入材料只作为临时定义上下文，不创建 source/candidate。

## Helper 调用

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" kb.knowledgebase.create '<payload-json>' --pretty
```

## 载荷

```json
{
  "title": "<non-empty title>",
  "description": "<reviewed description>",
  "tags": ["tag"],
  "scope": {"includes": [], "excludes": []},
  "default_outline_id": "<outline-id>",
  "outlines": [],
  "review": {"decision": "approve"}
}
```

必填 reviewed 字段：`title`、`review`、`description`、`tags`、`scope`、`default_outline_id`、`outlines`。

可选字段：`knowledgebase_id`、`input_path`。

## Resume / Review

- 返回 `needs_llm` 时，按 API 的 `llm_request` 生成 `description`、`tags`、`scope`、`default_outline_id` 和 `outlines` draft，并用同一 `resume_token` 恢复。
- 返回 `needs_review` 时，必须等待用户 approve 或 edited structured fields。

## Result 字段

报告 knowledgebase ID、knowledgebase path、outlines file、`objects.created`、`diffs`、`index_rebuild`、`warnings`、`errors` 和 `next_actions`。

## 硬规则

- 需要 review gate。
- 不得调用 `kb.source.add`。
- 不得调用 `kb.candidate.create`。
- 不要写入 `data/raw` 或 `data/cleaned`。
- 不要直接创建或编辑 knowledgebase files。
