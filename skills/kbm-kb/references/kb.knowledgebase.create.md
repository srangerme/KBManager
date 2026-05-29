# `kb.knowledgebase.create`

## 用途

创建 active knowledgebase 和配套 outlines YAML。输入材料只作为临时定义上下文，不创建 source/candidate。

## Helper 调用

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" kb.knowledgebase.create '<payload-json>' --pretty
```

## 载荷

```json
{
  "title": "<non-empty title>",
  "description": "<reviewed description>",
  "tags": ["tag"],
  "scope": {"includes": [], "excludes": []},
  "default_outline_id": "<outline-id>",
  "outlines": [],
  "review": {"decision": "approve"}
}
```

必填 reviewed 字段：`title`、`review`、`description`、`tags`、`scope`、`default_outline_id`、`outlines`。

可选字段：`knowledgebase_id`、`input_path`。

## Resume / Review

- 返回 `needs_llm` 时，按 API 的 `llm_request` 生成 `description`、`tags`、`scope`、`default_outline_id` 和 `outlines` draft，并用同一 `resume_token` 恢复。
- 返回 `needs_review` 时，必须等待用户 approve 或 edited structured fields。

## Resume token

`resume_token` 由 API 服务端生成，格式为：

```text
resume-kb.knowledgebase.create-<sha256(operation + normalized token payload) 前 24 位>
```

`kb.knowledgebase.create` 的 token payload 使用这些字段：

- `title`: 首次请求传入的 title。
- `input_path`: 首次请求传入的 input path，API 端使用 `str(input_path)`。
- `knowledgebase_id`: 首次请求传入的 knowledgebase ID，未传时为 `null`。
- `knowledgebase_create_input`: API 从 `input_path` 读取或解析出的临时创建上下文。

保证 token 一致：

- Resume 时必须使用第一次 `needs_llm` 返回的 `resume.token`，不要自行重新生成。
- Resume 请求里的 `title`、`input_path`、`knowledgebase_id` 必须和首次请求完全一致。
- 在 `needs_llm` 到 resume 之间，不要修改、移动或替换 `input_path` 指向的文件或目录；其解析内容会参与 token。
- `needs_review` 阶段继续使用同一次流程的 reviewed fields；不要把旧 token 混用到另一次 create 流程。

## Result 字段

报告 knowledgebase ID、knowledgebase path、outlines file、`objects.created`、`diffs`、`index_rebuild`、`warnings`、`errors` 和 `next_actions`。

## 硬规则

- 需要 review gate。
- 不得调用 `kb.source.add`。
- 不得调用 `kb.candidate.create`。
- 不要写入 `data/raw` 或 `data/cleaned`。
- 不要直接创建或编辑 knowledgebase files。
