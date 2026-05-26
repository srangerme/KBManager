# Interface

本文定义第一层 Interaction & Orchestration 的设计。第一层由 Claude Code、自定义 slash command、自然语言交互、结果展示和 user review 组成，负责把用户意图编排为第二层 `kb.*` API 调用。

除 `/clean` 迁移执行的特许例外外，第一层不直接修改 Markdown/PDF/YAML 对象文件，不直接维护对象状态机。所有知识库数据变更必须通过第二层 API 完成。

## 1. 第一层职责

第一层负责：

- 接收用户输入：slash command、自然语言、review 决策、备注。
- 使用 Claude Code 展示 list/view Markdown、review 草案和需要用户补充的内容。
- 通过 Claude Code 对话收集用户确认、修改后的 Markdown 或结构化字段。
- 组装交互层 LLM prompt：使用 KBManager 系统提示词约束角色、边界和输出，再叠加用户输入和必要对象上下文。
- 编排第二层 `kb.*` API。
- 接管 API 返回的 `needs_llm` 请求：读取系统提示词和对象上下文，结合本次用户输入调用 LLM，再用 `resume_token` 回传结果。
- 在需要 user review 的位置暂停。
- 展示执行结果、candidate 列表、问题清单、修复方案和问答引用。

第一层不得：

- 绕过 API 直接创建、修改、移动、删除对象文件；`/clean` 在展示完整迁移计划并获得用户整批确认后的迁移执行除外。
- 绕过 user review 修改正式 knowledge。
- 把索引文件当作事实来源。
- 在 `/check` 中自动修复对象文件。
- 物理删除 source、note、knowledge 等对象；删除语义统一使用 `deprecated`。

只读例外：

- Interface 层可以为展示和问答只读读取对象文件和索引文件，并通过 Claude Code 展示内容。
- 只读展示和 review 草案都不得打开 VSCode；需要用户编辑时通过 Claude Code 回复收集 reviewed content。
- 只读读取不得产生对象状态变化，不得把索引内容反向写入对象事实。
- 对象写入 API 会在成功写入后自动调用 `kb.index.rebuild` 重建派生索引；`/check` 直接调用 `kb.index.rebuild` 重建索引并报告一致性问题。Interface 层不得直接写索引文件。

## 2. Slash Command 清单

只暴露以下命令：

```txt
/init
/source add <path>
/source deprecate <source-id>
/candidate review [candidate-id]
/knowledgebase create <path-or-url>
/knowledgebase list [knowledgebase-id]
/knowledgebase map [knowledgebase-id]
/note add
/note list
/note view <note-id>
/note deprecate <note-id>
/check
/clean
```

其他细粒度能力只作为第二层 API 存在，不直接暴露为 slash command。

## 3. 输入与输出

标准输入来源：

- 命令参数，例如 `<path>`、`<source-id>`、`<note-id>`。
- 用户在 Claude Code 中回复的 reviewed Markdown、结构化字段或确认。
- 用户在 review 中选择的处理方式。
- 用户自然语言备注。

标准输出：

```yml
status: success | failed | needs_llm | needs_review | partial
summary: 人类可读摘要
api_calls:
  - name: kb.source.add
    status: success
objects:
  created: []
  updated: []
  deprecated: []
opened_in_vscode: []
displayed_in_claude:
  - path: indexes/note-index.md
    format: markdown
    content: "..."
requested_in_claude:
  - kind: reviewed_markdown
    action: accept_candidate
    instructions: "Reply with approve or edited Markdown."
errors: []
next_actions: []
```

输出规则：

- 成功时展示对象 ID、状态变化和下一步。
- 失败时展示失败 API、原因、是否有部分产物。
- review 时展示处理选项和影响范围。
- LLM 生成内容必须展示来源、证据和不确定点。
- deprecated 对象在状态变更结果和 review/check 提示中必须显式标记为过时/不推荐使用；默认列表索引可隐藏 deprecated 对象。

## 4. LLM Prompt 组装

第一层 prompt 用于交互和编排，不直接处理对象事实写入。用户侧不提供提示词文件。

prompt 由以下部分组成：

- KBManager 系统提示词：来自 KBManager 本体，定义 Claude Code 在本系统中的角色、边界、行为、输出格式和禁止事项。
- 用户输入和对象上下文：来自本次命令参数、自然语言、Claude Code reviewed Markdown、review 备注、对象摘要或索引摘要。

第一层系统提示词类型：

- `source-ingest.md`：在 `/source add` 中生成 source `summary`、`tags` 和清洗内容。
- `source-ingest-prompt-rewrite.md`：把临时 `user_prompt` 重写为安全的 prompt fragment。
- `candidate-create.md`：在 `kb.candidate.create` 中生成 candidate 草案。
- `candidate-review-assist.md`：在 `/candidate review` 中生成只读 review 辅助说明。
- `knowledge-merge-assist.md`：在 `/candidate review` 的 merge 分支中生成合并草案和 `bindto` 建议。
- `note-title.md`：为 note 生成标题。
- `clean-migration-plan.md`：为 `/clean` 根据工作区差异生成迁移计划。
- `knowledgebase-create.md`：在 `/knowledgebase create <path-or-url>` 阶段根据 source-like input 生成 knowledgebase 的 `description`、`tags`、`scope` 和 `outline` 草案。

内嵌在流程里的 LLM 能力不称为 skill；它们是 system prompt / internal prompt module，由 slash command 或 API `needs_llm` 固定触发。只有用户在 Claude Code 对话中可以直接触发的辅助能力才设计为 skill。

用户可直接触发的 skill：

- `knowledgebase-deep-research-prompt`：给定 knowledgebase ID 或 Markdown，根据 `description`、`scope` 和 `outline` 生成给 ChatGPT Deep Research 的提示词；提示词必须要求最终报告的参考列表显式列出原始链接 URL。

组装顺序：

```txt
KBManager system prompt
  -> current command/input
  -> API catalog and index summaries
  -> output schema
```

第一层 prompt 允许注入：

```yml
kbmanager_system_prompt: 交互层系统提示词
user_input: 用户原始输入
command: 当前 slash command
known_object_ids: 已识别对象 ID
api_catalog: 允许调用的 kb.* API 摘要
index_summaries: 必要索引摘要
constraints:
  - 只能通过 kb.* API 修改数据
  - `/check` 会调用 `kb.index.rebuild` 重建派生索引并报告一致性问题
  - deprecated 表示过时，不做物理删除
  - 正式 knowledge 变更必须 review
```

第一层 prompt 不应注入完整知识库正文。需要对象正文时，应调用 API 获取对象或让 Claude Code 展示对象 Markdown。

用户输入和对象上下文不能覆盖 KBManager 系统提示词中的安全边界、只读约束、review gate、API 写入边界和输出结构。

## 5. 接管 API 的 LLM 请求

当 API 返回：

```yml
status: needs_llm
llm_request: {}
resume:
  operation: kb.candidate.create
  token: resume-20260520-001
```

第一层必须：

1. 读取 `llm_request.system_prompt` 指定的 KBManager 系统提示词。
2. 读取 `llm_request.required_context` 指定的对象或摘要。
3. 结合本次用户输入，按 `llm_request.output_schema` 要求调用 LLM。
4. 将 LLM 输出作为 `llm_result`，连同 `resume.token` 交回 API。
5. 等待 API 校验和写入结果。

第一层不得把 `llm_result` 直接写入对象文件。

## 6. 命令定义

### `/init`

- 输入：无命令参数，目标目录默认为当前调用目录。
- 行为：在目标目录初始化 KBManager 受控工作区目录结构、模板目录和索引目录。
- API 编排：`kb.init`。
- 输出：创建的目录和文件列表、已存在且未覆盖的路径、下一步建议。
- 约束：不得覆盖已有用户文件；目标目录已包含兼容受控结构时应返回幂等结果；遇到同名非预期文件、不兼容结构、不安全路径或任何覆盖风险时直接失败并告知原因，不进入 review，不创建任何目录或文件。

### `/source add <path>`

- 输入：目录、文件路径或 URL；可选临时 `user_prompt`。
- 行为：解析输入，生成 source `summary`、`tags` 和 cleaned 内容，添加 source，生成一个或多个 candidate。
- API 编排：可选 prompt rewrite + user review -> `kb.source.add` -> 接管 `needs_llm` 并 resume -> `kb.candidate.create` -> 接管 `needs_llm` 并 resume。
- LLM：如果用户提供临时 `user_prompt`，Interface 先调用 LLM 将其理解、重写为安全的 source ingest prompt fragment，并等待用户确认；确认后把该 prompt fragment 追加到 source ingest LLM 请求中。`kb.source.add` 阶段必定返回 `needs_llm`，由 Claude Code 生成 source `summary`、`tags` 和 cleaned content 后 resume；`kb.candidate.create` 阶段再由 Claude Code 先阅读 active knowledgebase 的 `description/scope/outline`，再阅读 source 内容，生成 candidate draft list、`bindto` 建议和 `outline_change_suggestions` 后 resume。
- 约束：临时 `user_prompt` 只能影响查看重点、总结角度和清洗格式偏好，不得覆盖 KBManager 系统提示词、输出 schema、review gate、证据约束或 URL 最大打开深度。若输入是 URL，Interface / Claude Code 不得自行下载、打开浏览器、打印导出 PDF、抓取网页、保存 Markdown 或用本地文件路径重试；必须把原始 URL 直接传给 `kb.source.add`。URL 直连下载、Playwright PDF 兜底和 `data/failed` 失败报告均由 API 内部处理。若 API 返回失败，Interface 只汇报 API 的错误、`data/failed` 路径和下一步动作。
- 输出：source ID、source `summary`、`tags`、source.cleaned 摘要、candidate/knowledge ID 列表、`bindto` 和 outline 修改建议。

### `/source deprecate <source-id>`

- 输入：source ID 和用户给出的原因。
- 行为：把 source 标记为 deprecated，不物理删除。
- API 编排：`kb.source.deprecate`。
- 输出：source 状态、废弃原因、影响范围。

### `/candidate review [candidate-id]`

- 输入：可选 candidate ID；这里的 candidate ID 是全局 knowledge ID。
- 行为：如果未提供 ID，调用 `kb.candidate.next_pending` 按添加时间获取下一个 pending candidate；由 Claude Code 展示 candidate Markdown；由 Claude Code 生成 review 辅助说明；用户选择处理方式并可输入自然语言备注。
- 处理方式：`accept`、`reject`、`defer`、`merge`。
- LLM：必须执行。只在第一层根据 candidate、source 引用、相关 knowledge 和 knowledgebase `outline` 生成辅助说明、证据检查、`bindto` 检查、outline 修改建议解释和风险提示，不写入数据；第二层不再提供 candidate review 组合 API。
- API 编排：`kb.candidate.get` -> 用户选择 `reject` 时调用 `kb.knowledge.reject`，选择 `defer` 时调用 `kb.candidate.defer`；选择 `accept` 或 `merge` 时，Interface 先在 Claude Code 展示预填建议的 reviewed Markdown，等待用户回复确认或修改后，再调用 `kb.knowledge.accept` 或 `kb.knowledge.merge` 写入。
- Review 草案：accept/merge 的 Claude Code 草案预填 candidate `summary`、`content`、`evidence`、`bindto` 和 review 备注；用户可编辑标题、summary、content、`evidence`、`bindto` 和 merge targets。
- Outline 决策：candidate 如果包含 `outline_change_suggestions`，Interface 先展示并与用户交互确认是否采纳或暂缓。按当前边界，review 不自动修改 knowledgebase `outline`，`kb.knowledge.accept` 和 `kb.knowledge.merge` 也不会修改 outline；用户确认只用于记录 review 判断和决定本次是否继续 accept/merge。
- Knowledgebase 决策：candidate 创建时已经生成 `bindto` 建议；review 时 Interface 可补充只读建议，但最终只以用户在 Claude Code 中确认后的 `bindto` 为准。accept/merge 只写入 knowledge 的 `bindto`，knowledgebase 成员视图由索引派生；不会创建新的 knowledgebase、修改 knowledgebase 对象成员列表或提供独立成员维护流程。
- 输出：candidate 新状态；如接受或合并，展示生成或更新的 knowledge。

### `/knowledgebase create <path-or-url>`

- 输入：source-like input；input 格式与 `/source add` 相同，可以是目录、文件路径或 URL。
- 行为：先询问用户 title 并创建最小 knowledgebase，再用输入材料生成 create 阶段的 `description`、`tags`、`scope` 和 `outline`。
- API 编排：解析或收集 input -> 询问 title -> `kb.knowledgebase.create` -> `kb.knowledgebase.init` -> 接管 `needs_llm` 并生成 create 阶段草案 -> resume 交回 API 校验 -> API 返回 `needs_review` -> 在 Claude Code 展示草案 -> 用户确认或修改 -> 带 review 和 reviewed payload 再次 resume `kb.knowledgebase.init`。
- 约束：该输入不是 `source` 对象，不创建 `source-*`，不写入 `data/raw` 或 `data/cleaned`，不进入 source index，也不成为 knowledgebase 成员；它只作为本次初始化的临时上下文。URL 采集仍由 API 负责，Interface 不自行下载、打开浏览器、打印导出 PDF、抓取网页或保存 Markdown。
- 输出：knowledgebase ID、标题、create 阶段字段摘要、路径和自动索引重建结果。

### `/knowledgebase list [knowledgebase-id]`

- 输入：可选 knowledgebase ID。
- 行为：不带 ID 时由 Claude Code 展示全局 knowledgebase index；带 ID 时展示该 knowledgebase 的 knowledge index 文件。
- API 编排：无。Interface 层只读打开用户工作区中的派生 index；若索引不存在或过期，则提示运行 `/kbm:check`。
- 输出：展示的 index 路径和 Markdown 内容。

### `/knowledgebase map [knowledgebase-id]`

- 输入：可选 knowledgebase ID。
- 行为：根据 knowledgebase `outline` 和 knowledge `bindto` 生成 Mermaid 结构图，写入临时 Markdown 文件，并用 VSCode 打开。
- API 编排：`kb.knowledgebase.map`。
- 输出：临时 Markdown 路径、无效 bindto/outline 问题；如果 VSCode 不可用，则在 Claude Code 中展示路径和 Markdown 内容。

### `/note add`

- 输入：无命令参数。
- 行为：在 Claude Code 中收集 note Markdown；用户回复后提取内容。
- API 编排：`kb.note.add`。
- 输出：note ID、标题、状态。

### `/note list`

- 输入：无。
- 行为：由 Claude Code 展示 note index 文档。
- API 编排：无。Interface 层只读打开 note index 派生文档；若索引不存在或过期，则提示运行 `/kbm:check`。
- 输出：note index 路径或内容引用。

### `/note view <note-id>`

- 输入：note ID。
- 行为：由 Claude Code 展示 note Markdown。
- API 编排：`kb.note.get`。
- 输出：note 文件路径。

### `/note deprecate <note-id>`

- 输入：note ID 和原因。
- 行为：把 note 标记为 deprecated，不物理删除。
- API 编排：`kb.note.deprecate`。
- 输出：note 新状态。

### `/check`

- 输入：无。
- 行为：Interface 层调用 `kb.index.rebuild`，从对象文件重建派生索引，并返回 index 更新 diff 和一致性问题；命令只做固定 API 调用和结果展示。
- API 编排：`kb.index.rebuild()`。
- 输出：更新的索引路径、问题列表和修复方案；问题列表应覆盖无效 `bindto`、不存在的 outline 节点、legacy `acceptance_criteria`、legacy `kb_ids` 和 legacy relation `child_of`。
- 约束：不得直接写对象文件或索引文件；索引写入只允许通过 `kb.index.rebuild`。

### `/clean`

- 输入：无。
- 行为：Interface 层调用 `kb.clean.inspect` 只读扫描工作区差异；存在差异时接管 `needs_llm`，生成迁移计划。
- API 编排：`kb.clean.inspect()`；用户确认迁移执行后调用 `kb.index.rebuild()`。
- 输出：迁移计划、风险、执行结果和重建索引结果。
- 约束：`/clean` 是唯一允许 Claude Code 直接修改对象文件的特许迁移命令，且必须先展示完整计划并获得用户整批确认；其他命令仍必须通过 API 写入。
