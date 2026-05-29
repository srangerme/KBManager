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

## Resume token

`resume_token` 由 API 服务端生成，格式为：

```text
resume-kb.note.add-<sha256(operation + normalized token payload) 前 24 位>
```

`kb.note.add` 的 token payload 使用这些字段：

- `content`: 首次请求传入的 note 内容。
- `title`: API 端 strip 后的 title；未传或空白 title 为 `null`。
- `note_id`: 首次请求传入的 note ID，未传时为 `null`。

保证 token 一致：

- Resume 时必须使用第一次 `needs_llm` 返回的 `resume.token`，不要自行重新生成。
- Resume 请求里的 `content`、`title`、`note_id` 必须和首次请求保持一致；不要在生成 title 后顺手改正文。
- 空 title 必须省略，不要传 `title: ""`；API 会把空白 title 归一化为 `null`。
- `needs_llm` 到 resume 之间不要改 `content` 的空格、换行或 Markdown 标记；正文逐字参与 token。

## Result 字段

报告 note ID、path、title、`objects.created`、`diffs`、`index_rebuild`、`warnings`、`errors` 和 `next_actions`。

## 硬规则

- 没有 review gate。
- `content` 不能为空。
- 不要传 `title: ""`；空 title 必须省略。
- 不要直接写 note files。
