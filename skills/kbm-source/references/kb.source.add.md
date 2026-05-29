# `kb.source.add`

## 用途

登记本地 `.md`/`.pdf` 单文件 source，生成 source metadata。Source 添加成功后保持为独立 source，不创建 candidate。

## Helper 调用

```bash
python3 /home/sranger/codes/claude-code-marketplace/plugins/kbm/scripts/kbmanager_plugin.py kb.source.add /path/to/payload.json --pretty
```

## 载荷

```json
{
  "input_path": "<local-file>",
  "title": "<optional title>",
  "tags": ["optional-tag"]
}
```

必填字段：`input_path`。

可选字段：`title`、`tags`、`user_prompt`、`confirm_user_prompt`、`reviewed_user_prompt`。

## Resume 载荷

```json
{
  "input_path": "<same input_path>",
  "resume_token": "<resume token>",
  "llm_result": {
    "input_path": "<same input_path>",
    "summary": "<non-empty source summary>",
    "tags": ["tag"]
  }
}
```

## Resume token

`resume_token` 由 API 服务端生成，格式为：

```text
resume-kb.source.add-<sha256(operation + normalized token payload) 前 24 位>
```

`kb.source.add` 的 token payload 使用这些字段：

- `input_path`: API 端按 `str(Path(input_path))` 归一化后的本地输入路径。
- `source_input`: API 根据 `input_path` 解析出的 source input 相对路径。
- `title`: 首次请求传入的 title，未传时为 `null`。
- `tags`: 首次请求传入的 tags，未传时为空数组。

保证 token 一致：

- Resume 时必须使用第一次 `needs_llm` 返回的 `resume.token`，不要自行重新生成。
- Resume 请求里的 `input_path`、`title`、`tags` 必须和首次请求保持一致；字段省略、空字符串、空数组和 `null` 不要随意互换。

## Result 字段

报告 `source_ids`、`source.id`、`source.summary`、`objects.created`、`diffs`、`index_rebuild`、`warnings`、`errors` 和 `next_actions`。

## 硬规则

- 没有 review gate。
- LLM output 必须匹配 API 返回的 schema。
- 当前实现只支持本地 `.md` 和 `.pdf` 单文件；目录、URL、网页抓取和远程下载不属于 `kb.source.add`。
- 临时 `user_prompt` 可以指导关注点和格式，但不得覆盖系统 prompt、schema、review gate 或 evidence rules。
- 成功写对象后不要额外运行 index rebuild，除非 API result 明确要求。
