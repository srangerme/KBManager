# `kb.knowledgebase.create`

## 用途

使用已 review 的 payload 创建 active knowledgebase 和配套 outlines YAML。

## Helper 调用

```bash
python3 /home/sranger/codes/claude-code-marketplace/plugins/kbm/scripts/kbmanager_plugin.py kb.knowledgebase.create '<payload-json>' --pretty
```

## 载荷

```json
{
  "title": "<non-empty title>",
  "description": "<reviewed description>",
  "tags": ["tag"],
  "scope": {"includes": [], "excludes": []},
  "default_outline_id": "<outline-id>",
  "outlines": []
}
```

必填 reviewed 字段：`title`、`description`、`tags`、`scope`、`default_outline_id`、`outlines`。

可选字段：`knowledgebase_id`。

## Prepare / Revise

- 需要从 `input_path` 生成草案时，先调用 `kb.knowledgebase.create.prepare`。
- hook reject + note 或其他 review note 需要修改草案时，调用 `kb.knowledgebase.create.revise`。
- 本 API 只做最终写入；不要传 `input_path`、`resume_token`、`llm_result` 或 `review`。

## Resume token

`resume_token` 由 API 服务端生成，格式为：

```text
resume-kb.knowledgebase.create.prepare-<sha256(operation + normalized token payload) 前 24 位>
```

`kb.knowledgebase.create.prepare` 的 token payload 使用这些字段：

- `title`: 首次请求传入的 title。
- `input_path`: 首次请求传入的 input path，API 端使用 `str(input_path)`。
- `knowledgebase_id`: 首次请求传入的 knowledgebase ID，未传时为 `null`。
- `knowledgebase_create_input`: API 从 `input_path` 读取或解析出的临时创建上下文。

保证 token 一致：

- Resume 时必须使用第一次 `needs_llm` 返回的 `resume.token`，不要自行重新生成。
- Resume 请求里的 `title`、`input_path`、`knowledgebase_id` 必须和首次请求完全一致。
- 在 `needs_llm` 到 resume 之间，不要修改、移动或替换 `input_path` 指向的文件或目录；其解析内容会参与 token。
- prepare 成功后，使用返回的 reviewed fields 调用最终 `kb.knowledgebase.create`。

## Result 字段

报告 knowledgebase ID、knowledgebase path、outlines file、`objects.created`、`diffs`、`index_rebuild`、`warnings`、`errors` 和 `next_actions`。

## 硬规则

- 最终写入会由 Claude Code PreToolUse hook 触发审批并展示最终写入请求；不要在调用前额外要求一次 approve。
- hook approve 时执行本 API；hook reject 无 note 时停止，不写对象。
- hook reject + note 时，不执行原写入；把 note 回流到 `kb.knowledgebase.create.revise`，再用 revised payload 重新调用本 API。
- 不得调用 `kb.source.add`。
- 不得调用 `kb.candidate.create`。
- 不要写入 `data/raw` 或 `data/cleaned`。
- 不要直接创建或编辑 knowledgebase files。
