# `kb.knowledgebase.outline.archive`

## 用途

归档 non-default outline。

## Helper 调用

```bash
python3 /home/sranger/codes/claude-code-marketplace/plugins/kbm/scripts/kbmanager_plugin.py kb.knowledgebase.outline.archive '<payload-json>' --pretty
```

## 载荷

```json
{
  "knowledgebase_id": "kb-...",
  "outline_id": "workflow",
  "allow_existing_bindings": true
}
```

必填字段：`knowledgebase_id`、`outline_id`。只有用户明确接受 binding impact 时才传 `allow_existing_bindings: true`。

## Result 字段

报告 archived outline、affected bindings、`objects.updated`、`diffs`、`index_rebuild`、`warnings`、`errors` 和 `next_actions`。

## 硬规则

- 最终写入会由 Claude Code PreToolUse hook 触发审批。
- 不要 archive 当前 default outline。
- 不要物理删除 outline nodes。
- 不要修改 knowledge `bindto`。
