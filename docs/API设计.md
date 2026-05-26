# API 设计

本文定义第二层 Application API / Domain Service。第二层对 Interface 层暴露 `kb.*` API，通过第三层 Repository / Data Layer 管理 Markdown/PDF/YAML 对象文件。

第二层不依赖 Claude Code 对话上下文。它可以被 slash command、CLI、MCP server、脚本或测试调用。

## 1. 职责边界

第二层负责：

- 暴露知识库领域 API。
- 校验输入参数、对象存在性、引用合法性和状态转换。
- 执行 review gate。
- 分配对象 ID。
- 在需要 LLM 辅助时返回 `needs_llm` 请求，声明 prompt、上下文和输出 schema；实际 LLM 调用由 Claude Code 接管。
- 调用数据层读写对象文件、派生索引和运行记录。
- 返回结构化结果、错误、影响范围和修复建议。

第二层不得：

- 把索引当事实来源。
- 未经 review 修改正式 knowledge。
- 物理删除对象。
- 依赖 Interface 层对话上下文才能完成业务判断。

## 2. 通用契约

请求：

```yml
request_id: req-20260520-001
operation: kb.source.add
actor:
  type: user | llm | system
  id: user
arguments: {}
options:
  dry_run: false
context:
  trace_id: trace-20260520-001
```

响应：

```yml
status: success | failed | needs_llm | needs_review | partial
operation: kb.source.add
objects:
  created: []
  updated: []
  deprecated: []
diffs: []
warnings: []
errors: []
review:
  required: false
  options: []
next_actions: []
```

规则：

- API 必须返回结构化错误。
- 涉及写入的 API 应支持 `dry_run`。
- `needs_llm` 响应不得产生对象写入。
- `needs_review` 响应不得产生任何对象写入、状态变更或文件移动。
- 对象引用统一使用 ID。pending/deferred/rejected candidate 使用全局 knowledge ID；candidate 被 accept 后，原 candidate 文件被原子提升/迁移为正式 knowledge 文件，同一 ID 不得同时存在 candidate 文件和 knowledge 文件。

## 3. LLM 辅助机制

第二层 API 不直接调用 LLM。需要 LLM 辅助时，API 返回 `needs_llm`，由 Claude Code 负责组装 prompt、调用 LLM，并通过 `resume_token` 把结果交回 API 继续执行。用户侧不提供提示词文件。

流程：

```txt
Interface 调用 kb.* API
  -> API 校验入参和对象状态
  -> API 返回 needs_llm + llm_request
  -> Claude Code 读取系统提示词、用户输入和对象上下文
  -> Claude Code 调用 LLM
  -> Claude Code 用 resume_token 回传 llm_result
  -> API 校验 LLM 输出结构和业务规则
  -> API 写入对象或返回 needs_review
```

`needs_llm` 响应：

```yml
status: needs_llm
operation: kb.candidate.create
llm_request:
  id: llm-20260520-001
  purpose: create_candidate
  system_prompt: candidate-create
  required_context:
    - source-20260520-001
  output_schema: candidate_draft_list
  constraints:
    - must_preserve_upstream_refs
    - must_include_evidence
    - must_not_create_accepted_knowledge
    - must_return_structured_mapping
resume:
  operation: kb.candidate.create
  token: resume-20260520-001
```

resume 请求：

```yml
operation: kb.candidate.create
resume_token: resume-20260520-001
llm_result: {}
```

任何 LLM prompt 都由以下部分组成：

1. KBManager 系统提示词：由中台随代码发布，定义角色、边界、行为、输出格式、review gate、数据写入约束和错误处理规则。
2. 用户输入和对象上下文：来自命令输入、Claude Code reviewed content、review 备注，以及 API 读取到的对象内容和引用摘要。

KBManager 本体不保存用户数据。用户侧不提供提示词文件，API 不应请求 `user_prompt_refs`。

系统提示词类型：

- `source-ingest.md`
- `source-ingest-prompt-rewrite.md`
- `candidate-create.md`
- `note-title.md`
- `clean-migration-plan.md`
- `candidate-review-assist.md`
- `knowledge-merge-assist.md`
- `knowledgebase-create.md`

Claude Code 的组装顺序：

```txt
KBManager system prompt
  -> current user input
  -> object context from API
  -> required output schema
```

系统提示词优先级高于用户输入和对象上下文。用户输入和对象上下文不能覆盖系统提示词中的数据边界、review gate、事实来源、只读检查和输出结构约束。

API 在 `llm_request` 中允许要求 Claude Code 注入：

```yml
kbmanager_system_prompt: 中台系统提示词
current_user_input: 本次用户输入
object_frontmatter: 对象元数据
object_body: 必要正文片段
source_evidence: 可追溯证据
related_objects: 相关对象摘要
index_summaries: 派生索引摘要
output_schema: API 要求输出结构
constraints:
  - 不创造无法追溯事实
  - 不把索引当事实来源
  - 不直接生成 accepted knowledge
```

不允许注入：

- 与当前 API 无关的完整知识库。
- 索引中存在但对象文件中不存在的事实。
- 未经用户授权的私有材料。
- 用户工作区外的用户数据。
- 请求或读取用户侧提示词文件。

API 收到 `llm_result` 后必须校验：

- 输出符合 `output_schema`。
- 所有 source、candidate、knowledge、note 引用存在。
- 每条由 LLM 生成的事实性结论都必须携带可校验 evidence 引用。每个 evidence item 必须是 mapping，形如 `{source_id|object_id|id: <requested-source-or-note-id>, locator: <page/section/line>, quote|excerpt|snippet: <supporting text>}`；API 只校验证据引用存在、格式正确、来源状态可用和必填字段完整，不承担语义级事实判断。
- LLM 没有绕过 review gate 生成 accepted knowledge。
- 写入前仍满足对象状态机和一致性规则。

## 4. Init API

### `kb.init`

- 输入：目标目录，默认使用调用方当前工作目录；可选 `dry_run`。
- 读取：KBManager 发布包中的默认目录清单和模板文件。
- 写入：在目标目录创建受控工作区目录结构、`indexes/`、必要的空索引占位文件，以及每个初始化目录下的空 `KBM.ignore`；对象模板保留为 KBManager 发布包内的系统资源，不写入用户工作区。
- 默认创建路径：
  - `data/raw/md/`、`data/raw/pdf/`、`data/raw/html/`、`data/cleaned/`、`data/attachments/`、`data/attachments/url-captures/`、`data/failed/`
  - `candidates/pending/`、`candidates/rejected/`、`candidates/deferred/`
  - `knowledge/atomic/`、`knowledge/bases/`
  - `notes/active/`、`notes/deprecated/`
  - `indexes/knowledgebase/`
  - `.lark/logs/`
- 默认创建文件除索引和 `KBM.ignore` 占位外，还包括 `.lark/settings.json.example`，用于飞书/Lark 集成配置示例；`.lark/` 下不写入用户知识对象。
- LLM 辅助：不需要。
- Review gate：不需要。`kb.init` 不提供 review 分支，也不提供覆盖确认流程。
- 校验：目标目录必须可写；不得写入目标目录外；不得覆盖已有用户文件；重复执行必须幂等；初始化产物不得包含用户知识数据。写入前必须先完成冲突检测；只要发现同名非预期文件、不兼容结构或任何覆盖风险，就返回 `failed` 并说明原因，不创建任何目录或文件。
- 输出：初始化根目录、创建的目录和文件列表、已存在且保持不变的路径、冲突列表和下一步建议。
- 约束：`kb.init` 只创建工作区结构和模板占位，不创建 source、candidate、knowledge、note 等业务对象。

## 5. Source API

### `kb.source.add`

- 输入：目录、文件路径或 URL；可选标题、标签、作者。本地目录或文件可位于本机任意可读位置，不要求在 workspace 内。
- 读取：source 模板和输入资源。
- 写入：source 对象及其 `cleaned` 派生字段；URL 直连成功时原文保存为 `data/raw/html/*.html` + `.meta.yml`，URL 直连失败但 Playwright PDF 导出成功时保存为 `data/raw/pdf/*.pdf` + `.meta.yml`，PDF 原文保存为 `data/raw/pdf/*.pdf` + `.meta.yml`，Markdown 原文保存为 `data/raw/md/*.md`。
- LLM 辅助：必需。API 固定返回 `needs_llm`，由 Claude Code 在同一次 LLM 调用中生成 source 总结、cleaned content 和元数据建议后 resume。
- Interface 可在调用 `kb.source.add` 前处理可选临时 `user_prompt`：先由 LLM 重写为安全 prompt fragment，经用户确认后追加到 source ingest LLM 请求。该临时 prompt 不属于 `kb.source.add` 的持久化参数，也不得改变 API 的校验和写入语义。
- 校验：本地路径可读或 URL 可采集、类型支持、元数据事实来源唯一；`summary` 非空；`cleaned_content` 可追溯原始资源；元数据建议不能覆盖事实字段。workspace 边界只限制 KBManager 对象和派生文件的写入位置，不限制本地 source 输入文件的读取位置。URL 采集完全由 API 负责：先直连下载，失败后尝试 Playwright 打印导出 PDF；若两者都失败，API 不创建 source，并将错误汇总写入 `data/failed`。Interface / Claude Code 不得自行下载、浏览器导出、抓取、保存 Markdown 或用本地文件路径重试 URL。
- LLM 结果结构：单文件输入时 `llm_result` 必须包含 `input_path`、非空 `summary`、非空 `cleaned_content`；`cleaned_content` 必须包含请求的 `input_path`。目录输入产生多个 source 时，`llm_result.sources` 必须与请求的每个输入路径一一对应。`tags` 和 `authors` 如出现必须是字符串列表。
- 输出：source ID、source 摘要、source 内的 cleaned 派生字段引用、原始资源引用。

### `kb.source.deprecate`

- 输入：source ID、废弃原因、可选替代对象 ID。
- 读取：source、引用它的 candidate 和 knowledge。
- 写入：source `deprecated` 状态和废弃元数据；成功写入后 API 自动调用 `kb.index.rebuild` 重建派生索引。
- LLM 辅助：不需要。
- Review gate：需要 user 确认。
- 输出：deprecated source 和基于引用关系生成的影响列表。

## 6. Candidate API

### `kb.candidate.create`

- 输入：`source_ids` 和/或 `note_ids`，至少一个非空；每个 ID 必须指向已存在对象。source 可为 `raw`、`archived` 或 `deprecated`，deprecated source 会产生 warning 供 user review 时确认。
- 读取：上游对象、candidate 模板、已有 knowledgebase 摘要、`candidate-create.md`。
- 写入：一个或多个 pending candidate Markdown。
- LLM 辅助：需要。API 返回 `needs_llm`，Claude Code 生成 candidate draft list、tag 建议和 knowledgebase 归属建议后 resume。
- 校验：每个 candidate 必须有来源、证据和上游引用；candidate ID 必须是全局唯一的 knowledge ID，显式提供时必须形如 `knowledge-YYYYMMDD-001`，也可省略由 API 分配。
- LLM 结果结构：

```yaml
candidates:
  - id: knowledge-YYYYMMDD-001        # 可选；省略时由 API 分配
    title: non-empty string
    body: non-empty string
    source_refs: [source-YYYYMMDD-001]
    note_refs: []
    evidence:
      - source_id: source-YYYYMMDD-001 # 也可用 object_id 或 id
        locator: page/section/line
        quote: supporting text         # quote/excerpt/snippet 三者至少一个
    suggested_tags: []
    suggested_kb_ids: []               # 必须指向已有 knowledge-base ID
    relations: []                      # 无关系时传 []
    evidence_summary: optional string
    llm_notes: optional string
```

- `source_refs` 和 `note_refs` 必须保留请求中的上游 ID。`relations` 有值时每项必须形如 `{type: <relation-type>, target: <existing-knowledge-id>}`，`type` 只能是 `agrees`、`conflicts`、`related_to`、`child_of`；`target` 只能指向已有正式 knowledge，不能留空，不能指向 source、note、candidate 或本次新建 candidate。层级关系只使用 `child_of`，且每个对象最多一个 `child_of`。
- 输出：candidate/knowledge ID 列表、建议 tag、建议 knowledgebase ID。

### `kb.candidate.get`

- 输入：candidate/knowledge ID。
- 读取：candidate Markdown 和必要引用摘要。
- 写入：无。
- LLM 辅助：不需要。
- 输出：candidate 路径、frontmatter、正文摘要、引用对象。

### `kb.candidate.next_pending`

- 输入：可选过滤条件。
- 读取：pending candidate 或 review queue。
- 写入：无。
- LLM 辅助：不需要。
- 输出：按添加时间排序的下一个 pending candidate。

### `kb.candidate.defer`

- 输入：candidate/knowledge ID、延后原因或备注。
- 读取：candidate。
- 写入：candidate deferred 状态和 review 记录。
- LLM 辅助：不需要。
- Review gate：必须携带 user 的 defer 决策。
- 输出：deferred candidate。

## 7. Knowledge API

### `kb.knowledge.accept`

- 输入：candidate/knowledge ID、review 决策、review 备注、用户 review 后的标题、正文、tags、kb_ids 和关系。
- 读取：candidate、knowledge 模板、已有 knowledgebase 摘要。
- 写入：将 pending candidate 文件原子提升/迁移为正式 knowledge Markdown，更新 `type: knowledge`、`status: accepted`、review 字段和 `kb_ids`，并同步对应 knowledgebase 的 `knowledge_ids`；同一 ID 不保留 candidate 文件。成功写入后 API 自动调用 `kb.index.rebuild` 重建派生索引。
- LLM 辅助：不需要。tag 和 knowledgebase 建议在 `kb.candidate.create` 或 Interface review 辅助阶段生成，用户通过 Claude Code reviewed content 最终确认。
- Review gate：必须携带 user 的 accept 决策；写入内容必须来自用户在 Claude Code 确认后的 reviewed Markdown 或等价结构化输入。
- reviewed payload 校验：`title` 和 `body` 必须是非空字符串；`tags` 和 `kb_ids` 必须显式提供字符串列表，空值用 `[]`；`relations` 必须显式提供，空值用 `[]`，有关联时每项形如 `{type: <relation-type>, target: <existing-knowledge-id>}`，`type` 只能是 `agrees`、`conflicts`、`related_to`、`child_of`。每个 `kb_id` 必须指向已有 knowledge-base；每个对象最多一个 `child_of`。
- 输出：knowledge ID、写入 knowledge 的 `kb_ids` 列表。
- 约束：本 API 不创建 knowledgebase 对象，也不提供独立 add/remove 成员维护能力；只根据最终 `kb_ids` 同步已有 knowledgebase 的 `knowledge_ids`。

### `kb.knowledge.merge`

- 输入：pending candidate ID、目标 knowledge ID、review 决策、review 备注、用户 review 后的合并正文、tags、kb_ids 和关系。
- 读取：pending candidate、目标 knowledge、来源、关系、已有 knowledgebase 摘要。
- 写入：更新目标 knowledge，来源 candidate 变为 rejected 状态，更新目标 knowledge 的 `kb_ids`，并同步对应 knowledgebase 的 `knowledge_ids`；candidate ID 不生成同 ID knowledge 文件。成功写入后 API 自动调用 `kb.index.rebuild` 重建派生索引。
- LLM 辅助：不需要。合并方案、tag 建议和 knowledgebase 归属建议由 Interface 层在 Claude Code review 前生成。
- Review gate：必须携带 user 的 merge 决策；写入内容必须来自用户在 Claude Code 确认后的 reviewed Markdown 或等价结构化输入。
- reviewed payload 校验：`body` 必须是非空字符串；`tags`、`kb_ids`、`relations` 必须显式提供，空列表用 `[]`。`relations[].type` 只能是 `agrees`、`conflicts`、`related_to`、`child_of`；`relations[].target` 必须指向已有 knowledge；`kb_ids[]` 必须指向已有 knowledge-base。`target_knowledge_id` 必须是已 accepted 的 knowledge。
- 输出：合并后的目标 knowledge、被合入的 candidate ID 和写入 knowledge 的 `kb_ids` 列表。
- ID 规则：merge 到已有 knowledge 时，最终对象使用目标 knowledge ID；candidate 记录保留原 ID、状态为 `rejected`。同一 ID 不得同时存在 candidate 文件和 knowledge 文件。
- 约束：本 API 不创建 knowledgebase 对象，也不提供独立 add/remove 成员维护能力；只根据最终 `kb_ids` 同步已有 knowledgebase 的 `knowledge_ids`。

### `kb.knowledge.reject`

- 输入：candidate/knowledge ID、review 决策、拒绝原因。
- 读取：candidate。
- 写入：candidate rejected 状态和 review 记录。
- LLM 辅助：不需要。
- Review gate：必须携带 user 的 reject 决策。
- 输出：rejected candidate。

### `kb.knowledge.deprecate`

- 输入：knowledge ID、可选废弃原因。
- 读取：knowledge、knowledgebase、relations、source。
- 写入：knowledge deprecated 状态和废弃元数据；成功写入后 API 自动调用 `kb.index.rebuild` 重建派生索引。
- LLM 辅助：不需要。
- Review gate：必须有 user 确认。
- 输出：deprecated knowledge。

## 8. Knowledge Base API

### `kb.knowledgebase.create`

- 输入：用户 review 后的结构化字段：`title`、`description`、`acceptance_criteria`、可选 `tags`、可选 `body`、可选 `knowledgebase_id`。
- 读取：knowledgebase 模板、已有 knowledgebase 摘要。
- 写入：knowledgebase Markdown；成功写入后 API 自动调用 `kb.index.rebuild` 重建派生索引。
- LLM 辅助：不需要。Interface 层负责询问必要字段并调用 LLM 生成草案，用户 review 后再调用 API 写入。
- Review gate：必须携带 user 的 approve 决策。
- 校验：`title`、`description`、`acceptance_criteria` 必须是非空字符串；`tags` 如提供必须是字符串列表；显式 `knowledgebase_id` 必须形如 `kb-YYYYMMDD-001` 或 `kb-YYYYMMDD-001-title-slug` 且全局唯一；标题不能与已有 knowledge-base 重复。
- 输出：knowledgebase ID、路径。
- 约束：本 API 只创建 knowledgebase，不提供 knowledgebase add/remove 成员维护能力。

### `kb.knowledgebase.map`

- 输入：可选 `knowledgebase_id`、可选 `output_path`。
- 读取：accepted knowledge、knowledgebase 成员关系和 knowledge frontmatter 中的 `child_of` 关系。
- 写入：临时 Markdown 文件；不写入 repo-tracked index 或对象文件。
- LLM 辅助：不需要。
- Review gate：不需要，因为输出是派生视图。
- 输出：临时 Markdown 路径、Mermaid Markdown 内容和层级一致性问题。
- 约束：Mermaid 边方向为 parent -> child；`child_of` 表示当前 knowledge 是 target knowledge 的子节点。

## 9. Note API

### `kb.note.add`

- 输入：note Markdown 内容、可选标题和显式 note ID。
- 读取：note 模板。
- 写入：独立 note Markdown。
- LLM 辅助：可选。需要时返回 `needs_llm`，Claude Code 生成标题后 resume。
- 校验：`content` 必须是非空字符串；`title` 如提供必须非空；显式 `note_id` 必须形如 `note-YYYYMMDD-001` 或 `note-YYYYMMDD-001-title-slug` 且全局唯一。
- LLM 结果结构：`llm_result` 必须是 `{title: <non-empty string>}`。
- 写入字段：`id`、`type: note`、`title`、`status: active`、`deprecated_at`、`deprecated_reason`、`created`、`updated`。
- 输出：note ID、路径和 note 对象。

### `kb.note.get`

- 输入：note ID。
- 读取：note Markdown。
- 写入：无。
- LLM 辅助：不需要。
- 输出：note 路径、frontmatter、正文摘要。

### `kb.note.deprecate`

- 输入：note ID、废弃原因。
- 读取：note。
- 写入：note deprecated 状态和原因；将 note 文件移动到 `notes/deprecated/`。
- LLM 辅助：不需要。
- Review gate：需要 user 确认。
- 输出：deprecated note。

## 10. Index API

### `kb.index.rebuild`

- 输入：重建范围 `all | source | candidate | knowledge | knowledgebase | note | relation | review_queue`，可选对象 ID、`dry_run`。
- 读取：对象文件、frontmatter、`.meta.yml` 和引用关系。
- 写入：目标范围内的派生索引文件；`dry_run` 时不写入，只返回拟更新 diff。
- LLM 辅助：不需要。
- Review gate：不需要，因为索引是派生视图，不是事实来源。
- 输出：重建的索引路径、diff、发现的一致性问题和未修复项。
- 约束：不得把索引内容反向写回对象事实；对象文件和索引冲突时始终以对象文件为准。
- 调用方式：对象写入 API 会在成功写入后自动调用非 dry-run `kb.index.rebuild`。`/check` 也直接调用非 dry-run `kb.index.rebuild`，用于重建派生索引并返回一致性问题。

### `kb.clean.inspect`

- 输入：无。
- 行为：只读扫描当前工作区目录设计和对象字段，对比当前版本预期。
- LLM 辅助：存在差异时返回 `needs_llm`，Claude Code 根据差异生成迁移计划。
- 输出差异：缺失目录、legacy 目录、legacy 字段、legacy 状态、路径迁移和冲突风险。
- 约束：API 不执行迁移、不写对象文件；`/clean` 在展示完整迁移计划并获得用户整批确认后，才允许 Claude Code 直接修改文件。

## 11. Review Gate

必须阻止未确认写入的场景：

- source deprecated。
- candidate defer。
- knowledge accept/merge/reject/deprecate。
- knowledgebase create。
- note deprecated。

缺少 user review 时返回：

```yml
status: needs_review
review:
  required: true
  options:
    - approve
    - reject
    - revise
```
