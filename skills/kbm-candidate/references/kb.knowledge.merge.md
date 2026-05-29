# `kb.knowledge.merge`

## 用途

将 pending candidate 合并进已有 accepted knowledge。

## Helper 调用

```bash
python3 /home/sranger/codes/claude-code-marketplace/plugins/kbm/scripts/kbmanager_plugin.py kb.knowledge.merge '<payload-json>' --pretty
```

## 载荷

```json
{
  "candidate_id": "<candidate-id>",
  "target_knowledge_id": "<knowledge-id>",
  "summary": "<reviewed merged summary>",
  "content": "<reviewed merged content>",
  "evidence": [],
  "bindto": []
}
```

必填字段：`candidate_id`、`target_knowledge_id`、reviewed `summary`、`content`、`evidence`、`bindto`。

## Result 字段

报告 target knowledge ID、source candidate status、updated paths、`diffs`、`index_rebuild`、`warnings`、`errors` 和 `next_actions`。

## 硬规则

- 最终写入会由 Claude Code PreToolUse hook 触发审批并展示最终写入请求；不要在调用前额外要求一次 approve。
- hook approve 时执行本 API；hook reject 无 note 时停止，不写对象。
- hook reject + note 或其他修改 note 应先走 `kb.candidate.review.revise`，再用 revised payload 重新调用本 API。
- Merge 结果使用 target knowledge ID，不使用 candidate ID 作为正式 knowledge ID。
- Evidence 必须保持可追溯。
