# `kb.candidate.defer`

## 用途

将 pending candidate 标记为 deferred，保留后续处理空间。

## Helper 调用

```bash
python3 /home/sranger/codes/claude-code-marketplace/plugins/kbm/scripts/kbmanager_plugin.py kb.candidate.defer '<payload-json>' --pretty
```

## 载荷

```json
{
  "candidate_id": "<candidate-id>",
  "reason": "<optional reason>"
}
```

必填字段：`candidate_id`。

## Result 字段

报告 deferred candidate ID、`objects.updated` 或 moved paths、`diffs`、`index_rebuild`、`warnings`、`errors` 和 `next_actions`。

## 硬规则

- 最终写入会由 Claude Code PreToolUse hook 触发审批并展示最终写入请求；没有明确 defer 决定时不要调用。
- hook approve 时执行本 API；hook reject 无 note 时停止，不写对象。
- hook reject + note 不触发 `kb.candidate.review.revise`；把 note 作为新的 `reason` 或意图澄清，等待用户再次明确 defer，或停止流程。
- 不要直接移动或编辑 candidate 文件。
