# `kb.note.deprecate`

## 用途

将 note 标记为 deprecated。

## Helper 调用

```bash
python3 /home/sranger/codes/claude-code-marketplace/plugins/kbm/scripts/kbmanager_plugin.py kb.note.deprecate /path/to/payload.json --pretty
```

## 载荷

```json
{
  "note_id": "note-...",
  "reason": "<non-empty reason>"
}
```

必填字段：`note_id`、`reason`。

## Result 字段

报告 deprecated note ID、path、`objects.deprecated`、`diffs`、`index_rebuild`、`warnings`、`errors` 和 `next_actions`。

## 硬规则

- 最终写入会由 Claude Code PreToolUse hook 触发审批。
- 不要直接编辑、移动或删除 note files。
- 展示 deprecated notes 时应标记为过时。
