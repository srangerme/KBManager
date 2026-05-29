# `kb.knowledge.accept`

## 用途

将 pending candidate 提升为 accepted knowledge。

## Helper 调用

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" kb.knowledge.accept '<payload-json>' --pretty
```

## 载荷

```json
{
  "candidate_id": "<candidate-id>",
  "decision": "accept",
  "title": "<reviewed title>",
  "summary": "<reviewed summary>",
  "content": "<reviewed markdown content>",
  "evidence": [],
  "bindto": []
}
```

必填字段：`candidate_id`、`decision`、reviewed `title`、`summary`、`content`、`evidence`、`bindto`。

## Result 字段

报告 accepted knowledge ID、path、`objects.created`/`objects.updated`、`diffs`、`index_rebuild`、`warnings`、`errors` 和 `next_actions`。

## 硬规则

- 需要 review gate；必须等待用户 approve 或 edited reviewed content。
- `evidence` 必须来自 candidate upstream source evidence。
- 空 `bindto` 必须传 `[]`。
- 成功后不保留同 ID pending candidate。
