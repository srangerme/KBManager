# `kb.knowledge.accept`

## 用途

将 pending candidate 提升为 accepted knowledge。

## Helper 调用

```bash
python3 /home/sranger/codes/claude-code-marketplace/plugins/kbm/scripts/kbmanager_plugin.py kb.knowledge.accept '<payload-json>' --pretty
```

## 载荷

```json
{
  "candidate_id": "<candidate-id>",
  "title": "<reviewed title>",
  "summary": "<reviewed summary>",
  "content": "<reviewed markdown content>",
  "evidence": [],
  "bindto": []
}
```

必填字段：`candidate_id`、reviewed `title`、`summary`、`content`、`evidence`、`bindto`。

## Result 字段

报告 accepted knowledge ID、path、`objects.created`/`objects.updated`、`diffs`、`index_rebuild`、`warnings`、`errors` 和 `next_actions`。

## 硬规则

- 最终写入会由 Claude Code PreToolUse hook 触发审批并展示最终写入请求；不要在调用前额外要求一次 approve。
- hook approve 时执行本 API；hook reject 无 note 时停止，不写对象。
- hook reject + note 或其他修改 note 应先走 `kb.candidate.review.revise`，再用 revised payload 重新调用本 API。
- `evidence` 必须来自 candidate upstream source evidence。
- 空 `bindto` 必须传 `[]`。
- 成功后不保留同 ID pending candidate。
