# Interface

本文定义第一层 Interaction & Orchestration。第一层由 Claude Code UI、
`kbm-*` skills、自然语言交互、结果展示和 user review 组成，负责把用户意图编排为第二层 `kb.*` API 调用。

除 clean 迁移执行和 `kbm-kb-outline` 明确触发的 outline YAML 更新特许例外外，第一层不直接修改 Markdown/PDF/YAML 对象
文件，不直接维护对象状态机。所有知识库数据变更必须通过第二层 API 完成。

## 1. 第一层职责

第一层负责：

- 接收用户输入：自然语言、review 决策、备注。
- 识别用户意图，选择相关 `kbm-*` skill，形成可执行工作流。
- 使用 Claude Code UI 展示 list/view Markdown、review 草案和需要用户补充的内容。
- 在 Claude Code UI 中收集用户确认、选择、修改后的 Markdown 或结构化字段。
- 编排第二层 `kb.*` API。
- 接管 API 返回的 `needs_llm` 请求：使用 API 返回的 prompt/schema 调用 LLM，再用 `resume_token` 回传结果。
- 在需要 user review 的位置暂停。
- 展示执行结果、candidate 列表、问题清单、修复方案和问答引用。

第一层不得：

- 绕过 API 直接创建、修改、移动、删除对象文件；clean 迁移执行和 `kbm-kb-outline` 的受控 outline YAML 更新除外。
- 绕过 user review 修改正式 knowledge。
- 把索引文件当作事实来源。
- 在 check 中自动修复对象文件。
- 物理删除 source、note、knowledge 等对象；删除语义统一使用 deprecated、rejected、deferred 或 archived。

只读例外：

- Interface 层可以为展示和问答只读读取对象文件和索引文件。
- 只读展示和 review 草案不得打开 VSCode；需要用户编辑时通过 Claude Code UI 回复收集 reviewed content。
- `kb.knowledgebase.map` 是特许例外：它生成临时派生 Markdown 图，不修改对象或 repo-tracked index，可返回临时路径供本地打开。
- 只读读取不得产生对象状态变化，不得把索引内容反向写入对象事实。
- 对象写入 API 会在成功写入后自动调用 `kb.index.rebuild` 重建派生索引；check workflow 直接调用 `kb.index.rebuild`。

## 2. Commands

KBManager 不暴露 Claude Code commands。细粒度能力只作为 `kb.*` API、
skill workflow 或自然语言意图存在。

## 3. Skills

所有 KBManager skill 名称必须以 `kbm-` 开头。

- `kbm-basic`：目录结构、对象边界、文件职责、通用规则、禁令和受控直接编辑例外。
- `kbm-source`：source add、source deprecate。
- `kbm-candidate`：candidate create/get/next pending/review。
- `kbm-note`：note add/get/list/view/deprecate。
- `kbm-kb`：knowledgebase create/list/map。
- `kbm-kb-outline`：outline create/set-default/archive，以及用户显式要求时的受控 outline YAML 更新。
- `kbm-maintenance`：init、check、clean inspect 和 clean migration。
- `kbm-research-on`：根据 knowledgebase 的 `description`、`scope` 和 outline 生成 Deep Research prompt。

内嵌在流程里的 LLM 能力不称为 skill。它们是 `system-prompts/` internal prompt module，由 API `needs_llm` 或第一层 workflow 固定触发。

## 4. 输入与输出

标准输入来源：

- 用户自然语言请求。
- 用户在 Claude Code UI 中回复的 reviewed Markdown、结构化字段、确认或选择。
- API 返回的 resume token、review request、warnings 和 errors。

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
displayed_in_claude:
  - path: indexes/note-index.md
    format: markdown
    content: "..."
requested_in_claude:
  - kind: reviewed_markdown
    action: accept_candidate
    instructions: "Reply with approve or edited Markdown."
opened_in_vscode: []   # 仅 kb.knowledgebase.map 临时派生图可使用
errors: []
next_actions: []
```

输出规则：

- 成功时展示对象 ID、状态变化和下一步。
- 失败时展示失败 API、原因、是否有部分产物。
- review 时展示处理选项和影响范围。
- LLM 生成内容必须展示来源、证据和不确定点。
- deprecated 对象在状态变更结果和 review/check 提示中必须显式标记为过时或不推荐使用；默认列表索引可隐藏 deprecated 对象。

## 5. LLM Prompt 组装

用户侧不提供提示词文件。prompt 由以下部分组成：

- KBManager 系统提示词：来自 KBManager 本体，定义角色、边界、行为、输出格式和禁止事项。
- 用户输入和对象上下文：来自本次自然语言、Claude Code UI reviewed content、review 备注、对象摘要或 API 提供的对象内容。
- 输出 schema：由 API 或 workflow 指定。

系统提示词类型：

- `source-ingest.md`：生成 source `summary`、`tags` 和清洗内容。
- `candidate-create.md`：生成 pending candidate 草案。
- `note-title.md`：为 note 生成标题。
- `clean-migration-plan.md`：根据工作区差异生成迁移计划。
- `knowledgebase-create.md`：根据 source-like input 生成 knowledgebase 草案，由 `kb.knowledgebase.create` 的 `needs_llm` 返回。

组装顺序：

```txt
KBManager system prompt
  -> current user input
  -> object context from API or workflow
  -> output schema
```

用户输入和对象上下文不能覆盖 KBManager 系统提示词中的安全边界、只读约束、review gate、API 写入边界和输出结构。

## 6. 接管 API 的 LLM 请求

当 API 返回：

```yml
status: needs_llm
llm_request: {}
resume:
  operation: kb.candidate.create
  token: resume-20260520-001
```

第一层必须：

1. 使用 `llm_request` 中的 prompt、上下文和输出 schema。
2. 结合本次用户输入，但不得覆盖系统提示词。
3. 调用 LLM 并要求输出匹配 schema。
4. 将 LLM 输出作为 `llm_result`，连同 `resume.token` 交回 API。
5. 等待 API 校验和写入结果。

第一层不得把 `llm_result` 直接写入对象文件。

## 7. Review Gate Catalog

这些 API 或流程有 review gate：

- `kb.source.deprecate`
- `kb.candidate.defer`
- `kb.knowledge.accept`
- `kb.knowledge.reject`
- `kb.knowledge.merge`
- `kb.knowledge.deprecate`
- `kb.knowledgebase.create`
- `kb.knowledgebase.outline.create`
- `kb.knowledgebase.outline.set_default`
- `kb.knowledgebase.outline.archive`
- `kb.note.deprecate`
- clean 迁移执行

这些流程没有 review gate：

- `kb.init`
- `kb.source.add`
- `kb.candidate.create`
- `kb.note.add`
- `kb.candidate.get`
- `kb.candidate.next_pending`
- `kb.knowledgebase.map`
- `kb.note.get`
- `kb.index.rebuild`
- `kb.clean.inspect`
- list/view 只读展示


所有 `kb.*` API payload 必须包含：

```yml
```

规则：


## 9. Workflow Summary

- Init：`kb.init`。
- Source add：`kb.source.add` -> handle `needs_llm` -> 必然调用 `kb.candidate.create` -> handle `needs_llm`；该 workflow 的语义是导入 source 并创建 pending candidates。
- Note add：收集 content；用户未提供标题时通过 `kb.note.add` 触发 title `needs_llm`；随后 resume 并写入 note。
- Candidate review：`kb.candidate.get` 或 `kb.candidate.next_pending` -> skill 只读 review assist -> user decision -> review-gated API。
- Knowledgebase create：`kb.knowledgebase.create` -> handle `needs_llm` -> resume -> user review -> approved `kb.knowledgebase.create`。
- Outline create/set-default/archive：收集 ID 和 review -> matching outline API。
- List/view：只读展示对象或索引。
- Map：`kb.knowledgebase.map`。
- Check：`kb.index.rebuild`。
- Clean inspect：`kb.clean.inspect`; migration execution requires Claude Code UI approval.
