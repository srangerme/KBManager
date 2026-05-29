# `kb.knowledgebase.outline.set_default`

## 用途

将一个 active outline 设置为 knowledgebase default outline。

## Helper 调用

```bash
python3 /home/sranger/codes/claude-code-marketplace/plugins/kbm/scripts/kbmanager_plugin.py kb.knowledgebase.outline.set_default /path/to/payload.json --pretty
```

## 载荷

```json
{
  "knowledgebase_id": "kb-...",
  "outline_id": "workflow"
}
```

必填字段：`knowledgebase_id`、`outline_id`。

## Result 字段

报告 knowledgebase ID、updated default outline、`objects.updated`、`diffs`、`index_rebuild`、`warnings`、`errors` 和 `next_actions`。

## 硬规则

- 最终写入会由 Claude Code PreToolUse hook 触发审批。
- 目标 outline 必须存在且 active。
- 不要直接编辑 outline files。
- 不要修改 knowledge `bindto`。
