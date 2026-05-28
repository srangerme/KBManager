---
name: kbm-candidate
description: 当用户要求从 sources 创建 candidates、获取 candidate、显示下一个 pending item、审核 pending knowledge、accept、reject、defer、merge、approve、编辑 reviewed payload 或处理 candidate decisions 时使用此 skill。适用于 candidate create/get/next_pending/review/defer/reject/accept/merge、pending candidate 队列、review items、有 evidence 支撑的 candidate 内容，以及把 candidates 转为 accepted knowledge。此 skill 管理 candidate 生命周期动作和带 review gate 的 candidate 决策。
---

# KBManager Candidate Workflows

使用此 skill 时，必须明确告诉用户：`Using skill: kbm-candidate`。

## Candidate Create

- 通常跟随 source add。
- 使用 source IDs 调用 `kb.candidate.create`。
- 使用 API 提供的 prompt 和 schema 处理 `needs_llm`。
- 只创建 pending candidates。
- 没有 review gate。

## Candidate Get Or Next Pending

- 对指定 candidate 使用 `kb.candidate.get`。
- 当用户要求下一个 review item 时，从 Claude Code UI 使用 `kb.candidate.next_pending`。
- 两者都按只读处理。

## Candidate Review

当用户想要 accept、reject、defer、merge 或以其他方式 review candidate 时使用。

1. 获取 candidate。
2. 可选生成只读 review assistance。
3. 在 Claude Code UI 中展示 candidate content、evidence、bindto suggestions 和 options。
4. 收集明确的用户决定或编辑后的 reviewed payload。
5. 调用匹配的带 review gate 的 API。
6. 报告 accepted、rejected、deferred 或 merged 的 object IDs 和 warnings。
