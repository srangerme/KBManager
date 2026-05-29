# `kb.knowledgebase.outline.create`

## 用途

为 active knowledgebase 创建新的 active outline。

## Helper 调用

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" kb.knowledgebase.outline.create '<payload-json>' --pretty
```

## 载荷

```json
{
  "knowledgebase_id": "kb-...",
  "outline": {
    "id": "workflow",
    "title": "Workflow",
    "description": "Process-oriented view.",
    "status": "active",
    "nodes": []
  },
  "review": {"decision": "approve"}
}
```

必填字段：`knowledgebase_id`、`outline`、`review`。

## Result 字段

报告 knowledgebase ID、outline ID、outlines file、`objects.updated`、`diffs`、`index_rebuild`、`warnings`、`errors` 和 `next_actions`。

## 硬规则

- 需要 review gate。
- 不要直接编辑 knowledgebase 或 outline files 来创建 outline。
- 不要从 outline context 创建 source objects。
- 不要自动设置为 default outline。
