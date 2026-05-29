# `kb.candidate.defer`

## 用途

将 pending candidate 标记为 deferred，保留后续处理空间。

## Helper 调用

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" kb.candidate.defer '<payload-json>' --pretty
```

## 载荷

```json
{
  "candidate_id": "<candidate-id>",
  "reason": "<optional reason>",
  "decision": "defer"
}
```

必填字段：`candidate_id`、`decision`。

## Result 字段

报告 deferred candidate ID、`objects.updated` 或 moved paths、`diffs`、`index_rebuild`、`warnings`、`errors` 和 `next_actions`。

## 硬规则

- 需要 review gate；没有明确用户决定时不要调用。
- 不要直接移动或编辑 candidate 文件。
