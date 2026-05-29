# `kb.source.deprecate`

## 用途

将 source 标记为 deprecated，并保留历史引用链。

## Helper 调用

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" kb.source.deprecate '<payload-json>' --pretty
```

## 载荷

```json
{
  "source_id": "source-...",
  "reason": "<non-empty reason>",
  "decision": "deprecate"
}
```

必填字段：`source_id`、`reason`、`decision`。

## Result 字段

报告 `source_id`、`impacts`、`objects.deprecated`、`diffs`、`index_rebuild`、`warnings`、`errors` 和 `next_actions`。

## 硬规则

- 需要 review gate；没有明确用户确认时不要调用。
- 不要直接编辑 source metadata。
- 不要物理删除 source。
