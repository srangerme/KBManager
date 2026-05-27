# API 设计

本文定义第二层 Application API / Domain Service。第二层对 Interface 层暴露 `kb.*` API，通过第三层 Repository / Data Layer 管理 Markdown/PDF/YAML 对象文件。

第二层不依赖 Claude Code 对话上下文。它可以被 `/kbm:ask`、内部 JSON CLI、MCP server、脚本或测试调用。

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
entrypoint: claude_code
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
- 所有 API 请求必须携带 `entrypoint: claude_code`。
- 所有 API 请求必须携带 `dry_run: true | false`。`dry_run: true` 时只校验 payload、entrypoint、对象存在性、状态转换前置条件和 review gate 要求，不执行写入、文件移动或 LLM resume。
- API 必须在入口处校验 operation 是否允许当前 `entrypoint` 调用。不允许时返回 `failed`，错误中说明 operation、entrypoint 和允许入口。
- `needs_llm` 响应不得产生对象写入、状态变更或文件移动。采集类 API 可以在返回 `failed` 时写入诊断性失败报告，例如 `kb.source.add` 的 URL 采集失败报告写入 `data/failed/`；该失败报告不是 source、candidate、knowledge、knowledge base 或 note 对象，也不得被索引当作事实来源。
- `needs_review` 响应不得产生任何对象写入、状态变更或文件移动。
- 对象引用统一使用 ID。pending/deferred/rejected candidate 使用全局 knowledge ID；candidate 被 accept 后，原 candidate 文件被原子提升/迁移为正式 knowledge 文件，同一 ID 不得同时存在 candidate 文件和 knowledge 文件。

Entrypoint 规则：

- `claude_code` 可以调用所有 `kb.*` API，并负责 Claude Code UI review 交互。
- 设计上不再暴露外部聊天工具调用入口；历史实现若仍存在，不属于当前公开 API 契约。

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
  -> 无 review 要求时 API 写入对象
  -> 有 review 要求时 API 返回 needs_review 草案
  -> Claude Code 收集 user review 并用同一 resume_token 回传 reviewed_payload
  -> API 校验 review 决策和 reviewed_payload 后写入对象
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

带 review 的 resume 请求：

```yml
operation: <same operation returned by needs_llm>
resume_token: resume-20260520-001
llm_result: {}
review:
  decision: approve | reject | revise
  reviewed_at: 2026-05-20T14:30:05
reviewed_payload: {}
```

规则：

- `resume_token` 只表示继续同一次 API 流程，不表示用户已经批准写入。
- 对需要 LLM 且最终需要 user review 的写入 API，API 在收到 `llm_result` 后应先校验结构，再返回 `needs_review` 和待确认草案；缺少明确 review 决策时不得写入。
- 用户确认或修改后，Interface 必须用同一个 `resume_token` 回传 `review` 和 `reviewed_payload`。API 只使用 `reviewed_payload` 落盘，不直接把未经 review 的 `llm_result` 写入对象事实。
- `review.decision: approve` 才允许继续写入；`reject` 取消本次写入并返回 failed 或 success/noop；`revise` 要求 Interface 继续收集修改后的 reviewed payload。
- 只需要 LLM 但不需要 review 的 API，可以在校验 `llm_result` 后直接写入。只需要 review 但不需要 LLM 的 API，必须在初次请求或后续请求中携带 review 决策和必要 reviewed payload。

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
- 本次 schema 中声明的对象 ID 引用必须存在；LLM 事实性 `evidence` 只能引用本次 API 允许的上游 source。
- 每条由 LLM 生成的事实性结论都必须携带可校验 evidence 引用。每个 evidence item 必须是 mapping，形如 `{source_id|object_id|id: <requested-source-id>, locator: <page/section/line>, quote|excerpt|snippet: <supporting text>}`；API 只校验证据引用存在、格式正确、来源状态可用和必填字段完整，不承担语义级事实判断。
- LLM 没有绕过 review gate 生成 accepted knowledge。
- 写入前仍满足对象状态机和一致性规则。

## 4. Init API

### `kb.init`

- 输入：目标目录，默认使用调用方当前工作目录；必选 `entrypoint` 和 `dry_run`。
- 读取：KBManager 发布包中的默认目录清单和模板文件。
- 写入：在目标目录创建受控工作区目录结构、`indexes/`、必要的空索引占位文件，以及每个初始化目录下的空 `KBM.ignore`；对象模板保留为 KBManager 发布包内的系统资源，不写入用户工作区。
- 默认创建路径：
  - `data/raw/md/`、`data/raw/pdf/`、`data/raw/html/`、`data/cleaned/`、`data/attachments/`、`data/attachments/url-captures/`、`data/failed/`
  - `candidates/pending/`、`candidates/rejected/`、`candidates/deferred/`
  - `knowledge/atomic/`、`knowledge/bases/`
  - `notes/active/`、`notes/deprecated/`
  - `indexes/knowledgebase/`
- 默认创建文件为索引和 `KBM.ignore` 占位；历史外部聊天工具集成产物不属于当前公开初始化设计。
- LLM 辅助：不需要。
- Review gate：不需要。`kb.init` 不提供 review 分支，也不提供覆盖确认流程。
- 校验：目标目录必须可写；不得写入目标目录外；不得覆盖已有用户文件；重复执行必须幂等；初始化产物不得包含用户知识数据。写入前必须先完成冲突检测；只要发现同名非预期文件、不兼容结构或任何覆盖风险，就返回 `failed` 并说明原因，不创建任何目录或文件。
- 输出：初始化根目录、创建的目录和文件列表、已存在且保持不变的路径、冲突列表和下一步建议。
- 约束：`kb.init` 只创建工作区结构和模板占位，不创建 source、candidate、knowledge、note 等业务对象。

## 5. Source API

### `kb.source.add`

- 输入：目录、文件路径或 URL；必选 `entrypoint` 和 `dry_run`；可选标题和标签。本地目录或文件可位于本机任意可读位置，不要求在 workspace 内。
- 读取：source 模板和输入资源。
- 写入：source 对象字段 `id`、`type: source`、`title`、`source_type`、`status: raw`、`path`、`summary`、`cleaned`、`deprecated_at`、`deprecated_reason`、`tags`、`created`、`updated`；URL 直连成功时原文保存为 `data/raw/html/*.html` + `.meta.yml`，URL 直连失败但 Playwright PDF 导出成功时保存为 `data/raw/pdf/*.pdf` + `.meta.yml`，PDF 原文保存为 `data/raw/pdf/*.pdf` + `.meta.yml`，Markdown 原文保存为 `data/raw/md/*.md`。
- LLM 辅助：必需。API 固定返回 `needs_llm`，由 Claude Code 在同一次 LLM 调用中生成 source `summary`、`tags` 和 `cleaned_content` 后 resume。
- Interface 可在调用 `kb.source.add` 前处理可选临时 `user_prompt`：先由 LLM 重写为安全 prompt fragment，经用户确认后追加到 source ingest LLM 请求。该临时 prompt 不属于 `kb.source.add` 的持久化参数，也不得改变 API 的校验和写入语义。
- 校验：本地路径可读或 URL 可采集、类型支持、元数据事实来源唯一；`summary` 非空；`tags` 必须是字符串列表，空值用 `[]`；`cleaned_content` 可追溯原始资源；LLM 不得覆盖事实字段。workspace 边界只限制 KBManager 对象和派生文件的写入位置，不限制本地 source 输入文件的读取位置。URL 采集完全由 API 负责：先直连下载，失败后尝试 Playwright 打印导出 PDF；若两者都失败，API 返回 `failed`，不创建 source，不返回 `needs_llm`，并将错误汇总写入 `data/failed/` 作为诊断性失败报告。Interface / Claude Code 不得自行下载、浏览器导出、抓取、保存 Markdown 或用本地文件路径重试 URL。
- LLM 结果结构：单文件输入时 `llm_result` 必须包含 `input_path`、非空 `summary`、`tags` 字符串列表和非空 `cleaned_content`；`cleaned_content` 必须包含请求的 `input_path`。目录输入产生多个 source 时，`llm_result.sources` 必须与请求的每个输入路径一一对应，每项都必须包含 `input_path`、非空 `summary`、`tags` 和非空 `cleaned_content`。
- 输出：source ID、source `summary`、`tags`、source 内的 cleaned 派生字段引用、原始资源引用。

### `kb.source.deprecate`

- 输入：source ID、废弃原因、可选替代对象 ID。
- 读取：source、引用它的 candidate 和 knowledge。
- 写入：source `status: deprecated`、`deprecated_at`、`deprecated_reason` 和 `updated`；成功写入后 API 自动调用 `kb.index.rebuild` 重建派生索引。
- LLM 辅助：不需要。
- Review gate：需要 user 确认。
- 输出：deprecated source 和基于引用关系生成的影响列表。

## 6. Candidate API

### `kb.candidate.create`

- 输入：`source_ids`，至少一个非空；必选 `entrypoint` 和 `dry_run`。每个 ID 必须指向已存在 source。source 可为 `raw` 或 `deprecated`，deprecated source 会产生 warning 供后续 user review 时确认。
- 读取：上游 source、candidate 模板、active knowledge base 的 `description`、`tags`、`scope` 和 `outline`、`candidate-create.md`。
- 写入：一个或多个 pending candidate Markdown，字段包含 `id`、`type: candidate`、`title`、`status: pending`、`bindto`、`outline_change_suggestions`、`summary`、`evidence`、空 `review.reviewed_at`、空 `review.decision`、空 `review.reason`、`created`、`updated`。
- LLM 辅助：需要。API 返回 `needs_llm`，Claude Code 先依据已有 knowledge base 的 `description/scope/outline` 判断 source 中哪些内容符合已有知识库要求，再生成 candidate draft list、`bindto` 建议和 outline 修改建议后 resume；candidate 只能从 source 生成，不能从 note 生成。
- 校验：每个 candidate 必须有证据；candidate ID 必须是全局唯一的 knowledge ID，显式提供时必须形如 `knowledge-YYYYMMDD-001`，也可省略由 API 分配。
- LLM 结果结构：

```yaml
candidates:
  - id: knowledge-YYYYMMDD-001        # 可选；省略时由 API 分配
    title: non-empty string
    summary: non-empty string
    content: non-empty string
    evidence:
      - source_id: source-YYYYMMDD-001 # 也可用 object_id 或 id
        locator: page/section/line
        quote: supporting text         # quote/excerpt/snippet 三者至少一个
    bindto:
      - kb_id: kb-YYYYMMDD-001-title
        outline_id: canonical
        node_id: node-id
        reason: non-empty string
    outline_change_suggestions:
      - kb_id: kb-YYYYMMDD-001-title
        outline_id: canonical          # 可选；当建议针对某个现有 outline 时填写
        reason: non-empty string
        suggested_change: non-empty string
```

- `title`、`summary` 和 `content` 必须是非空字符串。candidate 和正式 knowledge 都只使用 `evidence` 追溯来源。`bindto[].kb_id` 必须指向已有 active knowledge base；`bindto[].outline_id` 必须指向该 knowledge base 的 active outline；`bindto[].node_id` 必须指向该 outline 的现有节点。若内容属于某个 knowledge base 的 `scope` 但当前 outline 无法覆盖，则不得伪造 `node_id`，应在 `outline_change_suggestions` 中说明建议如何修改。
- 输出：candidate/knowledge ID 列表、`bindto` 建议和 outline 修改建议。

### `kb.candidate.get`

- 输入：candidate/knowledge ID；必选 `entrypoint` 和 `dry_run`。
- 读取：candidate Markdown 和必要引用摘要。
- 写入：无。
- LLM 辅助：不需要。
- 输出：candidate 路径、frontmatter、正文摘要、引用对象。

### `kb.candidate.next_pending`

- 输入：必选 `entrypoint` 和 `dry_run`；当前不支持过滤条件。
- 读取：pending candidate 或 review queue。
- 写入：无。
- LLM 辅助：不需要。
- 输出：按添加时间排序的下一个 pending candidate。

### `kb.candidate.defer`

- 输入：candidate/knowledge ID、延后原因或备注；必选 `entrypoint` 和 `dry_run`。
- 读取：candidate。
- 写入：candidate `status: deferred`、`review.reviewed_at`、`review.decision`、`review.reason` 和 `updated`。
- LLM 辅助：不需要。
- Review gate：必须携带 user 的 defer 决策。
- 输出：deferred candidate。

## 7. Knowledge API

### `kb.knowledge.accept`

- 输入：candidate/knowledge ID、review 决策、review 备注、用户 review 后的标题、`summary`、`content`、`evidence` 和 `bindto`；必选 `entrypoint` 和 `dry_run`。
- 读取：candidate、knowledge 模板、已有 knowledge base 的 `outline` 摘要。
- 写入：将 pending candidate 文件原子提升/迁移为正式 knowledge Markdown，写入 `type: knowledge`、`status: accepted`、`summary`、`evidence`、review 字段和 `bindto`；同一 ID 不保留 candidate 文件。成功写入后 API 自动调用 `kb.index.rebuild`，由索引根据 knowledge `bindto` 派生 knowledge base 成员视图。
- LLM 辅助：不需要。`bindto` 和 outline 修改建议在 `kb.candidate.create` 或 Interface review 辅助阶段生成，用户通过 Claude Code reviewed content 最终确认。
- Review gate：必须携带 user 的 accept 决策；写入内容必须来自用户在 Claude Code 确认后的 reviewed Markdown 或等价结构化输入。
- reviewed payload 校验：`title`、`summary` 和 `content` 必须是非空字符串；`evidence` 必须来自 candidate 且至少引用一个 source；`bindto` 必须显式提供，空值用 `[]`，每项必须包含已有 active knowledge base ID 和有效 outline 节点。
- 输出：knowledge ID、写入 knowledge 的 `bindto` 列表。
- 约束：本 API 不创建 knowledge base 对象，不修改 knowledge base `outline`，也不提供独立 add/remove 成员维护能力；knowledge base 成员关系只由 knowledge `bindto` 表达，并通过索引派生展示。

### `kb.knowledge.merge`

- 输入：pending candidate ID、目标 knowledge ID、review 决策、review 备注、用户 review 后的合并 `summary`、`content`、`evidence` 和 `bindto`；必选 `entrypoint` 和 `dry_run`。
- 读取：pending candidate、目标 knowledge、来源和已有 knowledge base 的 `outline` 摘要。
- 写入：更新目标 knowledge 的 `summary`、`evidence`、正文、review 字段和 `bindto`，来源 candidate 变为 rejected 状态；candidate ID 不生成同 ID knowledge 文件。成功写入后 API 自动调用 `kb.index.rebuild`，由索引根据 knowledge `bindto` 派生 knowledge base 成员视图。
- LLM 辅助：不需要。合并方案和 `bindto` 建议由 Interface 层在 Claude Code review 前生成。
- Review gate：必须携带 user 的 merge 决策；写入内容必须来自用户在 Claude Code 确认后的 reviewed Markdown 或等价结构化输入。
- reviewed payload 校验：`summary` 和 `content` 必须是非空字符串；`evidence` 必须至少引用一个 source；`bindto` 必须显式提供，空列表用 `[]`。`bindto[].kb_id` 必须指向已有 active knowledge base，`outline_id` 必须指向 active outline，`node_id` 必须存在。`target_knowledge_id` 必须是已 accepted 的 knowledge。
- 输出：合并后的目标 knowledge、被合入的 candidate ID 和写入 knowledge 的 `bindto` 列表。
- ID 规则：merge 到已有 knowledge 时，最终对象使用目标 knowledge ID；candidate 记录保留原 ID、状态为 `rejected`。同一 ID 不得同时存在 candidate 文件和 knowledge 文件。
- 约束：本 API 不创建 knowledge base 对象，不修改 knowledge base `outline`，也不提供独立 add/remove 成员维护能力；knowledge base 成员关系只由 knowledge `bindto` 表达，并通过索引派生展示。

### `kb.knowledge.reject`

- 输入：candidate/knowledge ID、review 决策、拒绝原因；必选 `entrypoint` 和 `dry_run`。
- 读取：candidate。
- 写入：candidate `status: rejected`、`review.reviewed_at`、`review.decision`、`review.reason` 和 `updated`。
- LLM 辅助：不需要。
- Review gate：必须携带 user 的 reject 决策。
- 输出：rejected candidate。

### `kb.knowledge.deprecate`

- 输入：knowledge ID、可选废弃原因；必选 `entrypoint` 和 `dry_run`。
- 读取：knowledge、knowledgebase 和 source。
- 写入：knowledge `status: deprecated`、`deprecated_at`、`deprecated_reason` 和 `updated`；成功写入后 API 自动调用 `kb.index.rebuild` 重建派生索引。
- LLM 辅助：不需要。
- Review gate：必须有 user 确认。
- 输出：deprecated knowledge。

## 8. Knowledge Base API

### `kb.knowledgebase.create`

- 输入：`title`、经用户 review 确认后的 `description`、`tags`、`scope`、`default_outline_id`、`outlines`，必选 `entrypoint` 和 `dry_run`，可选 `knowledgebase_id`。
- 读取：knowledgebase 模板、已有 knowledgebase 摘要。
- 写入：active knowledgebase Markdown，以及同名 outlines YAML 文件。knowledgebase frontmatter 包含 `id`、`type: knowledge-base`、`title`、`status: active`、`description`、`tags`、`scope`、`default_outline_id`、`outlines_file`、`outlines` manifest、review 字段、`created` 和 `updated`；完整 outline 树写入 `outlines_file` 指向的 YAML 文件。成功写入后 API 自动调用 `kb.index.rebuild` 重建派生索引。
- LLM 辅助：API 本身不返回 `needs_llm`。knowledgebase create workflow 的 source-like input 由 Interface 临时读取或采集，并使用 `knowledgebase-create.md` 系统提示词生成草案；用户确认后，Interface 将 reviewed payload 交给本 API。
- Review gate：需要。缺少 `review.decision: approve` 时返回 `needs_review`，不得写入。
- 校验：`title` 和 `description` 必须是非空字符串；`tags` 必须是字符串列表；`scope` 必须明确包含和排除范围；显式 `knowledgebase_id` 必须形如 `kb-YYYYMMDD-001` 或 `kb-YYYYMMDD-001-title-slug` 且全局唯一；标题不能与已有 knowledge-base 重复；`default_outline_id` 必须指向一个 active outline；每个 outline 和可绑定 node 必须有稳定 ID。
- 输出：knowledgebase ID、Markdown 路径、outlines YAML 路径和自动索引重建结果。
- 约束：本 API 不创建 source 对象，不写入 `data/raw` 或 `data/cleaned`，不提供 knowledgebase add/remove 成员维护能力；knowledgebase 成员关系只由 knowledge `bindto` 表达。

### `kb.knowledgebase.outline.create`

- 输入：active knowledgebase ID、经用户 review 确认的新 outline；必选 `entrypoint` 和 `dry_run`。
- 读取：knowledgebase Markdown 和 `outlines_file`。
- 写入：向 outlines YAML 追加新 outline，并更新 knowledgebase frontmatter 中的 `outlines` manifest 和 `updated`；成功写入后 API 自动调用 `kb.index.rebuild`。
- Review gate：需要 `review.decision: approve`。
- 校验：knowledgebase 必须 active；outline ID 不得重复；outline 必须有非空 `id`、`title`、`description`、`status` 和节点列表；节点 ID 在该 outline 内必须唯一。

### `kb.knowledgebase.outline.set_default`

- 输入：active knowledgebase ID、active outline ID；必选 `entrypoint` 和 `dry_run`。
- 读取：knowledgebase Markdown 和 `outlines_file`。
- 写入：更新 knowledgebase frontmatter 和 outlines YAML 中的 `default_outline_id`；成功写入后 API 自动调用 `kb.index.rebuild`。
- Review gate：需要 `review.decision: approve`。
- 校验：目标 outline 必须存在且为 active。

### `kb.knowledgebase.outline.archive`

- 输入：active knowledgebase ID、非默认 outline ID，必选 `entrypoint` 和 `dry_run`，可选 `allow_existing_bindings`。
- 读取：knowledgebase Markdown、`outlines_file` 和现有 accepted knowledge 的 `bindto`。
- 写入：将目标 outline 状态置为 `archived`，并更新 knowledgebase frontmatter 中的 `outlines` manifest；成功写入后 API 自动调用 `kb.index.rebuild`。
- Review gate：需要 `review.decision: approve`。
- 校验：不得归档默认 outline；如果已有 knowledge 绑定到该 outline，除非用户明确允许 `allow_existing_bindings: true`，否则返回失败并列出影响。

### `kb.knowledgebase.map`

- 输入：必选 `entrypoint` 和 `dry_run`，可选 `knowledgebase_id`、`output_path`。
- 读取：active knowledgebase 的 `outlines_file`、`default_outline_id` 和 accepted knowledge 的 `bindto`。
- 写入：临时 Markdown 文件；不写入 repo-tracked index 或对象文件。
- LLM 辅助：不需要。
- Review gate：不需要，因为输出是派生视图。
- 输出：临时 Markdown 路径、从左到右展开的 Mermaid Markdown 内容、未绑定 knowledge、无效 outline 节点引用和其他结构一致性问题。
- 约束：Mermaid 图使用 `flowchart LR` 表达 outline 节点与绑定 knowledge 的结构；不从 knowledge relation 推导树状层级。

## 9. Note API

### `kb.note.add`

- 输入：note Markdown 内容，必选 `entrypoint` 和 `dry_run`，可选标题和显式 note ID。
- 读取：note 模板。
- 写入：独立 note Markdown。
- LLM 辅助：可选。用户提供非空 `title` 时可跳过；未提供标题时，Interface 应触发 `note-title.md`，由 Claude Code 生成标题后 resume。
- 校验：`content` 必须是非空字符串；`title` 如提供必须非空；显式 `note_id` 必须形如 `note-YYYYMMDD-001` 或 `note-YYYYMMDD-001-title-slug` 且全局唯一。
- LLM 结果结构：`llm_result` 必须是 `{title: <non-empty string>}`。
- 写入字段：`id`、`type: note`、`title`、`status: active`、`deprecated_at`、`deprecated_reason`、`created`、`updated`。
- 输出：note ID、路径和 note 对象。

### `kb.note.get`

- 输入：note ID；必选 `entrypoint` 和 `dry_run`。
- 读取：note Markdown。
- 写入：无。
- LLM 辅助：不需要。
- 输出：note 路径、frontmatter、完整正文 `body`。

### `kb.note.deprecate`

- 输入：note ID、废弃原因；必选 `entrypoint` 和 `dry_run`。
- 读取：note。
- 写入：note `status: deprecated`、`deprecated_at`、`deprecated_reason` 和 `updated`；将 note 文件移动到 `notes/deprecated/`。
- LLM 辅助：不需要。
- Review gate：需要 user 确认。
- 输出：deprecated note。

## 10. Index API

### `kb.index.rebuild`

- 输入：重建范围 `all | source | candidate | knowledge | knowledgebase | note | review_queue`，必选 `entrypoint` 和 `dry_run`，可选对象 ID。
- 读取：对象文件、frontmatter、`.meta.yml`、knowledgebase outlines YAML 和 knowledge `bindto`。
- 写入：目标范围内的派生索引文件；`dry_run` 时不写入，只返回拟更新 diff。
- LLM 辅助：不需要。
- Review gate：不需要，因为索引是派生视图，不是事实来源。
- 输出：重建的索引路径、diff、发现的一致性问题和未修复项；一致性问题必须覆盖无效 `bindto` 和不存在的 outline 节点。
- 约束：不得把索引内容反向写回对象事实；对象文件和索引冲突时始终以对象文件为准。
- 调用方式：对象写入 API 会在成功写入后自动调用非 dry-run `kb.index.rebuild`。check workflow 也直接调用非 dry-run `kb.index.rebuild`，用于重建派生索引并返回一致性问题。

### `kb.clean.inspect`

- 输入：必选 `entrypoint` 和 `dry_run`。
- 行为：只读扫描当前工作区目录设计和对象字段，对比当前版本预期。
- LLM 辅助：存在差异时返回 `needs_llm`，Claude Code 根据差异生成迁移计划。
- 输出差异：缺失目录、字段 schema drift、状态 drift、路径迁移和冲突风险；只检查当前新设计预期，不承担旧设计迁移。
- 约束：API 不执行迁移、不写对象文件；clean migration workflow 在展示完整迁移计划并获得用户整批确认后，才允许 Claude Code UI 直接修改文件。

## 11. Review Gate

必须阻止未确认写入的场景：

- source deprecated。
- candidate defer。
- knowledge accept/merge/reject/deprecate。
- knowledgebase create。
- knowledgebase outline create/set-default/archive。
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
