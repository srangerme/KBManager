# `kb.candidate.review.revise`

## 用途

根据用户 review note 或 accept/merge hook reject note 修订 candidate accept/merge 的 reviewed payload；不移动 candidate，不创建或更新 knowledge。

## Helper 调用

```bash
python3 /home/sranger/codes/claude-code-marketplace/plugins/kbm/scripts/kbmanager_plugin.py kb.candidate.review.revise /path/to/payload.json --pretty
```

## 载荷

```json
{
  "candidate_id": "<candidate-id>",
  "action": "accept",
  "current_payload": {},
  "review_note": "<user note>",
  "target_knowledge_id": "<required for merge>",
  "resume_token": "<only on resume>",
  "llm_result": {}
}
```

首次调用必填字段：`candidate_id`、`action`、`current_payload`、`review_note`。`action: "merge"` 时还必须传 `target_knowledge_id`。

## Result 字段

首次返回 `needs_llm`、`llm_request` 和 `resume.token`。Resume 成功后返回 revised `reviewed_payload`。

## 硬规则

- 没有 review gate，因为这是非写入修订 API。
- 只支持 `action: "accept"` 和 `action: "merge"`；reject/defer note 不走本 API。
- `evidence` 和 `bindto` 仍必须通过 API 校验。
- 修订后返回 revised payload；不要额外要求一次 approve，直接重新调用最终 accept/merge API，由 PreToolUse hook 展示和审批。
