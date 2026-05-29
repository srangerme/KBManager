# `kb.knowledge.reject`

## 用途

拒绝 pending candidate，不生成 accepted knowledge。

## Helper 调用

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" kb.knowledge.reject '<payload-json>' --pretty
```

## 载荷

```json
{
  "candidate_id": "<candidate-id>",
  "decision": "reject",
  "reason": "<optional reason>"
}
```

必填字段：`candidate_id`、`decision`。

## Result 字段

报告 rejected candidate ID、`objects.updated` 或 moved paths、`diffs`、`index_rebuild`、`warnings`、`errors` 和 `next_actions`。

## 硬规则

- 需要 review gate；没有明确 reject 决定时不要调用。
- 不要直接删除 candidate。
