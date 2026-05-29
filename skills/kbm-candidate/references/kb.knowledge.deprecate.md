# `kb.knowledge.deprecate`

## 用途

将 accepted knowledge 标记为 deprecated。

## Helper 调用

```bash
python3 /home/sranger/codes/claude-code-marketplace/plugins/kbm/scripts/kbmanager_plugin.py kb.knowledge.deprecate /path/to/payload.json --pretty
```

## 载荷

```json
{
  "knowledge_id": "knowledge-...",
  "reason": "<non-empty reason>"
}
```

必填字段：`knowledge_id`、`reason`。

## Result 字段

报告 deprecated knowledge ID、path、`objects.deprecated`、`diffs`、`index_rebuild`、`warnings`、`errors` 和 `next_actions`。

## 硬规则

- 最终写入会由 Claude Code PreToolUse hook 触发审批；用户意图明确时不要额外要求一次确认。
- 不要物理删除 accepted knowledge。
- 展示 deprecated knowledge 时标记为过时或不推荐。
