# `kb.candidate.create`

## 用途

从已有 source IDs 创建 pending candidates。通常由 `kbm-source` 在 `kb.source.add` 成功后强制调用。

## Helper 调用

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" kb.candidate.create '<payload-json>' --pretty
```

## 载荷

```json
{
  "source_ids": ["source-..."]
}
```

必填字段：`source_ids`。

## Resume 载荷

```json
{
  "source_ids": ["source-..."],
  "resume_token": "<resume token>",
  "llm_result": {
    "candidates": []
  }
}
```

Candidate draft 必须包含 API schema 要求的 `title`、`summary`、`content`、`evidence`、`bindto` 和可选 `outline_change_suggestions`。

## Result 字段

报告 candidate IDs、created paths、`warnings`、`errors`、`diffs`、`index_rebuild`、`bindto` suggestions、outline suggestions 和 `next_actions`。

## 硬规则

- 没有 review gate。
- 只创建 pending candidates，不创建 accepted knowledge。
- Evidence 必须可追溯到 upstream source。
