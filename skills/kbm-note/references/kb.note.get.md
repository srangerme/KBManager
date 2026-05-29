# `kb.note.get`

## 用途

按 note ID 定位 note object，用于查看完整 Markdown。

## Helper 调用

```bash
python3 /home/sranger/codes/claude-code-marketplace/plugins/kbm/scripts/kbmanager_plugin.py kb.note.get '<payload-json>' --pretty
```

## 载荷

```json
{
  "note_id": "note-..."
}
```

必填字段：`note_id`。

## Result 字段

报告 `note.id`、`note.path`、metadata、`warnings` 和 `errors`。

## 硬规则

- 只读操作。
- 成功后读取并展示 `note.path` 的完整 Markdown，包括 frontmatter 和 body。
- 不要用 summary 替代 note body。
