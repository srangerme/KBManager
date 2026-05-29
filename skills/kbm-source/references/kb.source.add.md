# `kb.source.add`

## 用途

登记 file、directory 或 URL source，生成 source metadata 和 cleaned content。Source 添加成功后，领域 workflow 必须继续调用 `kb.candidate.create` 创建 pending candidates。

## Helper 调用

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" kb.source.add '<payload-json>' --pretty
```

## 载荷

```json
{
  "input_path": "<file-directory-or-url>",
  "title": "<optional title>",
  "tags": ["optional-tag"],
  "authors": ["optional author"]
}
```

必填字段：`input_path`。

可选字段：`title`、`tags`、`authors`、`user_prompt`、`confirm_user_prompt`、`reviewed_user_prompt`。

## Resume 载荷

```json
{
  "input_path": "<same input_path>",
  "resume_token": "<resume token>",
  "llm_result": {
    "input_path": "<same input_path>",
    "summary": "<non-empty source summary>",
    "tags": ["tag"],
    "cleaned_content": "<non-empty cleaned markdown that references input_path>"
  }
}
```

Directory input 的 `llm_result` 使用：

```json
{
  "sources": [
    {
      "input_path": "<one requested input path>",
      "summary": "<non-empty source summary>",
      "tags": ["tag"],
      "cleaned_content": "<non-empty cleaned markdown that references input_path>"
    }
  ]
}
```

## Result 字段

报告 `source_ids`、`source.id`、`source.summary`、`source.cleaned_path`、`sources[]`、`objects.created`、`diffs`、`index_rebuild`、`warnings`、`errors` 和 `next_actions`。

## 硬规则

- 没有 review gate。
- LLM output 必须匹配 API 返回的 schema。
- URL input 直接交给 API；Claude Code 不得自行下载、打开、浏览、打印、导出、抓取、保存或重试 URL。
- 临时 `user_prompt` 可以指导关注点和格式，但不得覆盖系统 prompt、schema、review gate、evidence rules 或 URL-depth limits。
- 成功写对象后不要额外运行 index rebuild，除非 API result 明确要求。
