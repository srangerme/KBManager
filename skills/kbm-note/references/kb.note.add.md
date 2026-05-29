# `kb.note.add`

## 用途

创建 note，用于个人观察、临时笔记和工作记录。

## Helper 调用

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" kb.note.add '<payload-json>' --pretty
```

## 载荷

```json
{
  "content": "<non-empty markdown body>",
  "title": "<optional non-empty title>",
  "needs_llm": true
}
```

必填字段：`content`。可选字段：`title`、`needs_llm`。

## Resume 载荷

```json
{
  "content": "<same content>",
  "resume_token": "<resume token>",
  "llm_result": {"title": "<non-empty title>"}
}
```

## Result 字段

报告 note ID、path、title、`objects.created`、`diffs`、`index_rebuild`、`warnings`、`errors` 和 `next_actions`。

## 硬规则

- 没有 review gate。
- `content` 不能为空。
- 不要传 `title: ""`；空 title 必须省略。
- 不要直接写 note files。
