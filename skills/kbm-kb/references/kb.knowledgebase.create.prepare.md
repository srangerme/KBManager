# `kb.knowledgebase.create.prepare`

## 用途

从临时输入材料生成 knowledgebase 草案；不创建 source/candidate，不写 knowledgebase 文件。

## Helper 调用

```bash
python3 /home/sranger/codes/claude-code-marketplace/plugins/kbm/scripts/kbmanager_plugin.py kb.knowledgebase.create.prepare /path/to/payload.json --pretty
```

## 载荷

```json
{
  "title": "<non-empty title>",
  "input_path": "<file-or-directory>",
  "knowledgebase_id": "<optional kb-id>",
  "resume_token": "<only on resume>",
  "llm_result": {}
}
```

首次调用必填字段：`title`、`input_path`。Resume 时携带同一 `title`、`input_path`、可选 `knowledgebase_id`、`resume_token` 和 `llm_result`。

## Result 字段

首次返回 `needs_llm`、`llm_request` 和 `resume.token`。Resume 成功后返回 `reviewed_payload` / `knowledgebase_draft`，不写对象文件。

## 硬规则

- 没有 review gate，因为这是非写入准备 API。
- 不得调用 `kb.source.add` 或 `kb.candidate.create`。
- 返回 payload 后不要额外要求一次 approve；最终创建由 `kb.knowledgebase.create` 的 PreToolUse hook 展示和审批。
- hook reject + note 不是 prepare 的 resume；应把当前 payload 和 note 交给 `kb.knowledgebase.create.revise`。
