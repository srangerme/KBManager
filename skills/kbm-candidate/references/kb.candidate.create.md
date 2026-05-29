# `kb.candidate.create`

## 用途

从已有 source IDs 创建 pending candidates。输入必须是已存在的 source IDs。

## Helper 调用

```bash
python3 /home/sranger/codes/claude-code-marketplace/plugins/kbm/scripts/kbmanager_plugin.py kb.candidate.create '<payload-json>' --pretty
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

## Resume token

`resume_token` 由 API 服务端生成，格式为：

```text
resume-kb.candidate.create-<sha256(operation + normalized token payload) 前 24 位>
```

`kb.candidate.create` 的 token payload 使用这些字段：

- `source_ids`: 首次请求传入的 source ID 列表，顺序也参与 token。
- `active_knowledgebases`: API resume 时读取到的 active knowledgebase 上下文。
- `source_context`: API resume 时读取到的 source 上下文。

保证 token 一致：

- Resume 时必须使用第一次 `needs_llm` 返回的 `resume.token`，不要自行重新生成。
- Resume 请求里的 `source_ids` 必须和首次请求完全一致，包括列表顺序。
- 在 `needs_llm` 到 resume 之间，不要创建、删除、修改 active knowledgebase、outline 或相关 source 对象；这些上下文会参与 token。
- 如果出现 `invalid_resume_token`，应重新调用 `kb.candidate.create` 获取新的 `needs_llm` 和 token，而不是复用旧 token。

## Result 字段

报告 candidate IDs、created paths、`warnings`、`errors`、`diffs`、`index_rebuild`、`bindto` suggestions、outline suggestions 和 `next_actions`。

## 硬规则

- 没有 review gate。
- 只创建 pending candidates，不创建 accepted knowledge。
- Evidence 必须可追溯到 upstream source。
