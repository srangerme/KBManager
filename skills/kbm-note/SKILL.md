---
name: kbm-note
description: 当用户要求 add、capture、save、title、get、list、view、show 或 deprecate KBManager notes 时使用此 skill。适用于 note add、note title generation、personal notes、observations、scratch notes、note list/view/get/deprecate、deprecated note display，以及涉及 notes 但不作为 candidate creation evidence sources 的请求。此 skill 用于 note 生命周期动作，不用于 source ingestion 或有 evidence 支撑的 candidate creation。
---

# KBManager Note Workflows

使用此 skill 时，必须明确告诉用户：`Using skill: kbm-note`。

## Note Add

- 从用户或消息中收集 note content。
- 如果用户提供了非空 title，使用该 title 调用 `kb.note.add`。
- 如果没有提供 title，以 title-generation flow 调用 `kb.note.add`，
  根据 `note-title.md` 生成 `{"title": "<non-empty>"}`，然后 resume。
- 没有 review gate。

## Note Get And View

- 对指定 note 使用 `kb.note.get`。
- List/view display 可以读取 object files 或 indexes，但仅用于展示。
- 展示 deprecated notes 时标记为 outdated。
- 不要将 notes 作为 candidate creation 的 source evidence。

## Note Deprecate

- 需要 Claude Code UI。
- 需要明确的 review gate。
- 只有在获得明确用户批准后才调用 `kb.note.deprecate`。
