# `kb.knowledgebase.outline.set_default`

## 用途

将一个 active outline 设置为 knowledgebase default outline。

## Helper 调用

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" kb.knowledgebase.outline.set_default '<payload-json>' --pretty
```

## 载荷

```json
{
  "knowledgebase_id": "kb-...",
  "outline_id": "workflow",
  "review": {"decision": "approve"}
}
```

必填字段：`knowledgebase_id`、`outline_id`、`review`。

## Result 字段

报告 knowledgebase ID、updated default outline、`objects.updated`、`diffs`、`index_rebuild`、`warnings`、`errors` 和 `next_actions`。

## 硬规则

- 需要 review gate。
- 目标 outline 必须存在且 active。
- 不要直接编辑 outline files。
- 不要修改 knowledge `bindto`。
