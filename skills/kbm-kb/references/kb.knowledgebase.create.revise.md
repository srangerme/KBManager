# `kb.knowledgebase.create.revise`

## 用途

根据用户 review note 修订 knowledgebase 草案；不写对象文件。

## Helper 调用

```bash
python3 /home/sranger/codes/claude-code-marketplace/plugins/kbm/scripts/kbmanager_plugin.py kb.knowledgebase.create.revise /path/to/payload.json --pretty
```

## 载荷

```json
{
  "title": "<non-empty title>",
  "current_payload": {},
  "review_note": "<user note>",
  "knowledgebase_id": "<optional kb-id>",
  "resume_token": "<only on resume>",
  "llm_result": {}
}
```

首次调用必填字段：`title`、`current_payload`、`review_note`。Resume 时携带同一输入和 `resume_token` / `llm_result`。

## Result 字段

首次返回 `needs_llm`、`llm_request` 和 `resume.token`。Resume 成功后返回 revised `reviewed_payload`。

## 硬规则

- 没有 review gate，因为这是非写入修订 API。
- 只根据用户 note 修订草案，不批准最终创建。
- 修订后返回 revised payload；不要额外要求一次 approve，直接用 revised payload 调用最终 `kb.knowledgebase.create`，由 PreToolUse hook 展示和审批。
- hook reject + note 可以作为本 API 的 `review_note`；hook reject 无 note 时停止流程。
