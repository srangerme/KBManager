# `kb.knowledge.deprecate`

## 用途

将 accepted knowledge 标记为 deprecated。

## Helper 调用

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" kb.knowledge.deprecate '<payload-json>' --pretty
```

## 载荷

```json
{
  "knowledge_id": "knowledge-...",
  "reason": "<non-empty reason>",
  "decision": "deprecate"
}
```

必填字段：`knowledge_id`、`reason`、`decision`。

## Result 字段

报告 deprecated knowledge ID、path、`objects.deprecated`、`diffs`、`index_rebuild`、`warnings`、`errors` 和 `next_actions`。

## 硬规则

- 需要 review gate；没有明确确认时不要调用。
- 不要物理删除 accepted knowledge。
- 展示 deprecated knowledge 时标记为过时或不推荐。
