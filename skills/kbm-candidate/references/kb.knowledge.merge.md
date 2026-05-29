# `kb.knowledge.merge`

## 用途

将 pending candidate 合并进已有 accepted knowledge。

## Helper 调用

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" kb.knowledge.merge '<payload-json>' --pretty
```

## 载荷

```json
{
  "candidate_id": "<candidate-id>",
  "target_knowledge_id": "<knowledge-id>",
  "decision": "merge",
  "summary": "<reviewed merged summary>",
  "content": "<reviewed merged content>",
  "evidence": [],
  "bindto": []
}
```

必填字段：`candidate_id`、`target_knowledge_id`、`decision`、reviewed `summary`、`content`、`evidence`、`bindto`。

## Result 字段

报告 target knowledge ID、source candidate status、updated paths、`diffs`、`index_rebuild`、`warnings`、`errors` 和 `next_actions`。

## 硬规则

- 需要 review gate；必须等待用户 approve 或 edited reviewed content。
- Merge 结果使用 target knowledge ID，不使用 candidate ID 作为正式 knowledge ID。
- Evidence 必须保持可追溯。
