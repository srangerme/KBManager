---
name: kbm-maintenance
description: 当用户要求初始化 KBManager workspace、检查一致性、重建 indexes、检查 layout/schema cleanliness、clean 或 migrate repository、生成或执行 migration plan、验证 object/index state，或通过已批准 migration 修复结构问题时使用此 skill。适用于 kb.init、kb.index.rebuild、kb.clean.inspect、clean migration、init/check/clean/migrate、derived index rebuilding 和已 review 的 maintenance plans。
---

# KBManager Maintenance Workflows

使用此 skill 时，必须明确告诉用户：`Using skill: kbm-maintenance`。

## Init

- 从 Claude Code UI 使用。
- 调用 `kb.init`。
- 没有 review gate。
- 报告 created structure 和 warnings。

## Check

- 调用 `kb.index.rebuild`。
- 将该操作视为 consistency checking 和 derived index rebuilding。
- 除非用户请求单独的 reviewed workflow，否则不要自动修复 object files。

## Clean Inspect And Migration

- 调用 `kb.clean.inspect` 执行只读 layout/schema inspection。
- Plan generation 可以使用 `needs_llm`。
- Migration execution 需要 Claude Code UI 对完整 migration plan 的批准。
- Clean migration execution 是受控 direct-edit exception。
