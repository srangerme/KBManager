---
name: kbm-usage
description: 任何 KBManager、/kbm:ask、kb.* API、scripts/kbmanager_plugin.py、workspace、repository、object file、Markdown/YAML/PDF/HTML data、source/candidate/knowledge/note/knowledgebase、safe write、read-only view、direct edit、review gate、API payload、JSON result、needs_llm、resume_token、needs_review、review options、operation IDs、warnings/errors/diffs/next_actions、URL source、evidence、derived index、delete/deprecate/archive、clean migration、outline YAML exception、对象边界、事实来源、索引、删除、废弃、审核、写入边界、数据目录、状态机、权限或“能不能直接改文件/怎么调用 API”问题都应先使用此 skill。所有领域 workflow 在 API 调用、object writes、file edits、migration 或判断读写边界前触发。
---

# KBManager Usage

使用此 skill 时，必须明确告诉用户：`Using skill: kbm-usage`。

这是所有 KBManager 工作流的 usage skill。任何领域 skill 都不能覆盖这里的写入边界、事实来源、API 调用契约和 review gate。

## Repository Model

- KBManager 将用户数据存为 Markdown、PDF、HTML、YAML 和派生索引文件。
- Object files 是事实来源；derived indexes 只用于定位、展示和一致性检查。
- Claude Code UI 和 `/kbm:ask` 负责理解意图、选择 skill、展示草案、收集 user review、调用 `kb.*` API 并报告结果。
- `scripts/kbmanager_plugin.py` 是 Claude Code UI 调用 `kb.*` API 的 JSON helper。

## Object Types

- Source：原始材料或元数据，状态为 `raw` 或 `deprecated`。
- Candidate：从 source 生成的 pending/rejected/deferred 候选知识，使用预分配的 global knowledge ID。
- Knowledge：review 后的 accepted/deprecated 原子知识。
- Knowledgebase：组织 accepted knowledge 的主题对象，配套 outlines YAML。
- Note：个人记录、观察或 scratch note，不作为 candidate creation evidence。
- Index：派生视图，不是事实来源，不能反向写回 object facts。

## Write Boundaries

- 对 source、candidate、knowledge、knowledgebase、note 和 index writes 使用 `kb.*` APIs。
- 不要直接创建、编辑、移动或删除 KBManager object files。
- 不要物理删除 objects。删除语义使用 deprecate、reject、defer 或 archive。
- Object write APIs 成功后会自动 rebuild indexes；不要为同一写入额外运行 index rebuild，除非 API result 明确要求。
- List/view/read-only workflows 可以读取 object files 或 indexes 用于展示，但不得产生对象状态变化。

## Direct-Edit Exceptions

只有两个受控例外允许绕过普通 object write API：

- Clean migration execution：完整 migration plan 已在 Claude Code UI 展示并获得用户明确批准后，可以按 plan 直接编辑文件。
- Outline YAML maintenance：用户明确要求更新现有 outline YAML nodes 时，按 `kbm-kb` 中的 outline YAML direct-edit 规则操作。

这些例外不得用于创建新 source/candidate/knowledge/note，不得绕过 review gate，不得物理删除对象。

## Helper Contract

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kbmanager_plugin.py" <kb.operation> '<payload-json>' --pretty
```

- `<payload-json>` 必须是 JSON object。

## Result Handling

所有 API result 都按以下外层格式处理：

```json
{
  "status": "success | failed | needs_llm | needs_review | partial",
  "operation": "kb.operation.name",
  "objects": {
    "created": ["relative/path.md"],
    "updated": ["relative/path.md"],
    "deprecated": ["relative/path.md"]
  },
  "diffs": [
    {"action": "create | update | move | delete", "kind": "object-or-index", "path": "relative/path"}
  ],
  "warnings": ["warning text"],
  "errors": [
    {
      "operation": "kb.operation.name",
      "code": "machine_readable_code",
      "message": "human readable message",
      "suggestion": "optional recovery suggestion"
    }
  ],
  "review": {"required": false, "options": []},
  "next_actions": ["next action text"]
}
```

Operation-specific fields are merged at the top level beside the common
fields. Common operation-specific fields include object IDs, object payloads,
paths, maps, issues, `resume.token`, and index rebuild summaries.

When a write API succeeds and rebuilds indexes, it may include:

```json
{
  "index_rebuild": {
    "status": "success | partial | failed",
    "updated": ["indexes/path.md"],
    "index_paths": ["indexes/path.md"],
    "issues": []
  }
}
```

报告结果时保留 status、operation、object IDs、diffs、warnings、errors、review options 和 next actions。

## LLM Boundary

- 当 API 返回 `status: "needs_llm"`，按 API result 中的请求生成结构化 `llm_result`。
- 使用同一个 `resume_token` 恢复同一个 operation。
- 不要把 `llm_result` 直接写入 object files。
- 如果 resume 后返回 `needs_review`，必须继续执行 review gate，而不是默认写入。
- `needs_llm` result 只把 LLM 请求当作 opaque request 处理；skill 文档和用户报告中不要暴露内部 prompt 内容、内部 prompt 名称或内部 schema 定义。

外层格式：

```json
{
  "status": "needs_llm",
  "operation": "kb.operation.name",
  "warnings": [],
  "next_actions": ["Run LLM request ..., then resume kb.operation.name."],
  "resume": {"operation": "kb.operation.name", "token": "resume-kb.operation.name-..."}
}
```

## Review Boundary

- 没有明确用户批准时，不要继续带 review gate 的流程。
- `resume_token` 只表示继续同一次 API 流程，不表示用户已经批准写入。
- 当 API 返回 `needs_review` 时，在 Claude Code UI 中暂停，展示 proposed action、review options、影响范围、草案或 diff。
- 只有用户明确批准、选择或提交 reviewed payload 后，才调用对应写入 API 或 resume。

外层格式：

```json
{
  "status": "needs_review",
  "operation": "kb.operation.name",
  "review": {"required": true, "options": ["approve", "revise", "reject"]},
  "next_actions": ["Provide a user review decision before retrying this operation."]
}
```

## API Catalog

每个 API 的输出都是 common result envelope 加 operation-specific top-level
fields。下面的 `Result output fields` 使用精确字段路径描述输出格式；
`objects.*` 和 `diffs[]` 仍按 common envelope 处理。

### `kb.init`

- 用途：初始化 workspace structure。
- Review gate：无。
- Payload:

```json
{}
```

- Result output fields: `status`, `operation`, `objects.created`, `warnings`, `errors`,
  `diffs`, and `next_actions`. Conflicts are reported as `status: "failed"`
  with `warnings` and `diffs`; initialization does not overwrite conflicting
  paths.

### `kb.source.add`

- 用途：添加 file、directory 或 URL source。
- Review gate：无。领域工作流成功后继续 `kb.candidate.create`。
- 约束：URL 采集由 API 负责；Claude Code 不自行 fetch、browse、export、scrape、save 或 retry URL。
- Payload:

```json
{  "input_path": "<file-directory-or-url>",
  "title": "<optional title>",
  "tags": ["optional-tag"],
  "authors": ["optional author"]
}
```

- Resume payload when `status` is `needs_llm`:

```json
{  "input_path": "<same input_path>",
  "resume_token": "<resume token>",
  "llm_result": {
    "input_path": "<same input_path>",
    "summary": "<non-empty source summary>",
    "tags": ["tag"],
    "cleaned_content": "<non-empty cleaned markdown that references input_path>"
  }
}
```

For directory input, `llm_result` must use:

```json
{
  "sources": [
    {
      "input_path": "<one requested input path>",
      "summary": "<non-empty source summary>",
      "tags": ["tag"],
      "cleaned_content": "<non-empty cleaned markdown that references input_path>"
    }
  ]
}
```

- Result output fields: `source_ids`, `source.id`, `source.summary`,
  `source.cleaned_path`, `sources[].id`, `sources[].summary`,
  `sources[].cleaned_path`, `objects.created`, `diffs`, `index_rebuild`,
  `warnings`, `errors`, `next_actions`.

### `kb.source.deprecate`

- 用途：废弃 source。
- Review gate：需要。
- Payload:

```json
{  "source_id": "source-...",
  "decision": "deprecate",
  "reason": "<non-empty reason>"
}
```

- Result output fields: `source_id`, `impacts`, `objects.deprecated`, `diffs`,
  `index_rebuild`, `warnings`, `errors`, `next_actions`.

### `kb.candidate.create`

- 用途：从 source IDs 创建 pending candidates。
- Review gate：无。
- Payload:

```json
{  "source_ids": ["source-..."]
}
```

- Resume payload when `status` is `needs_llm`:

```json
{  "source_ids": ["source-..."],
  "resume_token": "<resume token>",
  "llm_result": {
    "candidates": [
      {
        "id": "knowledge-YYYYMMDD-001",
        "title": "<non-empty title>",
        "summary": "<non-empty summary>",
        "content": "<non-empty markdown content>",
        "evidence": [
          {
            "source_id": "source-...",
            "locator": "<page/section/line>",
            "quote": "<supporting text>"
          }
        ],
        "bindto": [
          {
            "kb_id": "kb-YYYYMMDD-001",
            "outline_id": "canonical",
            "node_id": "node-id",
            "reason": "<non-empty reason>"
          }
        ],
        "outline_change_suggestions": [
          {
            "kb_id": "kb-YYYYMMDD-001",
            "outline_id": "canonical",
            "reason": "<non-empty reason>",
            "suggested_change": "<non-empty change suggestion>"
          }
        ]
      }
    ]
  }
}
```

- Result output fields: `candidate_ids`, `candidates[].id`,
  `candidates[].bindto`, `candidates[].outline_change_suggestions`, flattened
  `bindto`, flattened `outline_change_suggestions`, `objects.created`, `diffs`,
  `index_rebuild`, `warnings`, `errors`, `next_actions`.

### `kb.candidate.get`

- 用途：读取指定 candidate。
- Review gate：无，只读。
- Payload:

```json
{"candidate_id": "knowledge-..."}
```

- Result output fields: `candidate.id`, `candidate.path`,
  `candidate.frontmatter`, `candidate.body`, `candidate.body_summary`,
  `candidate.references`, `warnings`, `errors`.

### `kb.candidate.next_pending`

- 用途：读取下一个 pending candidate。
- Review gate：无，只读。
- Payload:

```json
{}
```

- Result output fields: `candidate` object with the same shape as
  `kb.candidate.get`, or `candidate: null` when the pending queue is empty;
  `warnings`, `errors`, `next_actions`.

### `kb.candidate.defer`

- 用途：延后 pending candidate。
- Review gate：需要。
- Payload:

```json
{  "candidate_id": "knowledge-...",
  "decision": "defer",
  "reason": "<optional reason>"
}
```

- Result output fields: `candidate_id`, `candidate_status`, `objects.updated`,
  `diffs`, `index_rebuild`, `warnings`, `errors`, `next_actions`.

### `kb.knowledge.accept`

- 用途：将 pending candidate promote 为 accepted knowledge。
- Review gate：需要。
- Payload:

```json
{  "candidate_id": "knowledge-...",
  "decision": "accept",
  "reason": "<optional reason>",
  "title": "<reviewed title>",
  "summary": "<reviewed summary>",
  "content": "<reviewed markdown content>",
  "evidence": [
    {"source_id": "source-...", "locator": "<page/section/line>", "quote": "<supporting text>"}
  ],
  "bindto": [
    {"kb_id": "kb-...", "outline_id": "canonical", "node_id": "section-1", "reason": "<binding reason>"}
  ]
}
```

- Result output fields: `knowledge_id`, `bindto`, `objects.created`, `diffs`,
  `index_rebuild`, `warnings`, `errors`, `next_actions`.

### `kb.knowledge.reject`

- 用途：reject pending candidate。
- Review gate：需要。
- Payload:

```json
{  "candidate_id": "knowledge-...",
  "decision": "reject",
  "reason": "<optional reason>"
}
```

- Result output fields: `candidate_id`, `candidate_status`, `objects.updated`,
  `diffs`, `index_rebuild`, `warnings`, `errors`, `next_actions`.

### `kb.knowledge.merge`

- 用途：merge pending candidate into existing accepted knowledge。
- Review gate：需要。
- Payload:

```json
{  "candidate_id": "knowledge-...",
  "target_knowledge_id": "knowledge-...",
  "decision": "merge",
  "reason": "<optional reason>",
  "title": "<optional reviewed title>",
  "summary": "<reviewed summary>",
  "content": "<reviewed markdown content>",
  "evidence": [
    {"source_id": "source-...", "locator": "<page/section/line>", "quote": "<supporting text>"}
  ],
  "bindto": []
}
```

- Result output fields: `knowledge_id`, `rejected_candidate_id`, `bindto`,
  `objects.updated`, `diffs`, `index_rebuild`, `warnings`, `errors`,
  `next_actions`.

### `kb.knowledge.deprecate`

- 用途：deprecate accepted knowledge。
- Review gate：需要。
- Payload:

```json
{  "knowledge_id": "knowledge-...",
  "decision": "deprecate",
  "reason": "<optional reason>"
}
```

- Result output fields: `knowledge_id`, `objects.deprecated`, `diffs`,
  `index_rebuild`, `warnings`, `errors`, `next_actions`.

### `kb.knowledgebase.create`

- 用途：创建 active knowledgebase 和 outlines YAML。
- LLM boundary：初始 draft 阶段需要 `needs_llm`；resume 后进入 review gate。
- Review gate：需要。不创建 source/candidate。
- Initial payload:

```json
{  "title": "<knowledgebase title>",
  "input_path": "<temporary definition file-directory-or-url>",
  "knowledgebase_id": "kb-..."
}
```

- Resume payload when `status` is `needs_llm`:

```json
{  "title": "<same title>",
  "input_path": "<same input_path>",
  "resume_token": "<resume token>",
  "llm_result": {
    "frontmatter": {
      "description": "<non-empty description>",
      "tags": ["tag"],
      "scope": {"includes": ["..."], "excludes": ["..."]},
      "default_outline_id": "canonical",
      "outlines": []
    },
    "body": "<review draft body>"
  }
}
```

- Approved write payload:

```json
{  "title": "<knowledgebase title>",
  "knowledgebase_id": "kb-...",
  "description": "<reviewed description>",
  "tags": ["tag"],
  "scope": {"includes": ["..."], "excludes": ["..."]},
  "default_outline_id": "canonical",
  "outlines": [
    {"id": "canonical", "title": "Canonical", "description": "...", "status": "active", "nodes": []}
  ],
  "review": {"decision": "approve"}
}
```

- Result output fields: `knowledgebase_id`, `path`, `outlines_file`,
  `objects.created`, `diffs`, `index_rebuild`, `warnings`, `errors`,
  `next_actions`.

### `kb.knowledgebase.outline.create`

- 用途：给 active knowledgebase 增加 outline。
- Review gate：需要。
- Payload:

```json
{  "knowledgebase_id": "kb-...",
  "outline": {"id": "workflow", "title": "Workflow", "description": "...", "status": "active", "nodes": []},
  "review": {"decision": "approve"}
}
```

- Result output fields: `knowledgebase_id`, `outline_id`, `path`,
  `outlines_file`, `objects.updated`, `diffs`, `index_rebuild`, `warnings`,
  `errors`.

### `kb.knowledgebase.outline.set_default`

- 用途：设置 active outline 为 default。
- Review gate：需要。
- Payload:

```json
{  "knowledgebase_id": "kb-...",
  "outline_id": "workflow",
  "review": {"decision": "approve"}
}
```

- Result output fields: `knowledgebase_id`, `outline_id`, `objects.updated`,
  `diffs`, `index_rebuild`, `warnings`, `errors`, `next_actions`.

### `kb.knowledgebase.outline.archive`

- 用途：archive non-default outline。
- Review gate：需要。
- Payload:

```json
{  "knowledgebase_id": "kb-...",
  "outline_id": "workflow",
  "allow_existing_bindings": false,
  "review": {"decision": "approve"}
}
```

- Result output fields: `knowledgebase_id`, `outline_id`, `bound_knowledge`,
  `objects.updated`, `diffs`, `index_rebuild`, `warnings`, `errors`,
  `next_actions`.

### `kb.knowledgebase.map`

- 用途：生成临时 Mermaid knowledge map。
- Review gate：无；不修改 object facts。
- Payload:

```json
{  "knowledgebase_id": "kb-...",
  "output_path": "/tmp/kbmanager-map.md"
}
```

- Result output fields: `path`, `markdown`, `issues`, `knowledgebase_id`,
  `warnings`, `errors`.

### `kb.note.add`

- 用途：添加 active note。
- Review gate：无；没有 title 时可走 `needs_llm` title flow。
- Payload:

```json
{  "content": "<note markdown body>",
  "title": "<optional title>",
  "note_id": "note-...",
  "needs_llm": false
}
```

- Resume payload when title generation is requested:

```json
{  "content": "<same content>",
  "title": "<optional title>",
  "note_id": "note-...",
  "needs_llm": true,
  "resume_token": "<resume token>",
  "llm_result": {"title": "<non-empty title>"}
}
```

- Result output fields: `note_id`, `path`, `note.id`, `note.path`,
  `note.frontmatter`, `note.body`, `objects.created`, `diffs`,
  `index_rebuild`, `warnings`, `errors`, `next_actions`.

### `kb.note.get`

- 用途：读取 note。
- Review gate：无，只读。
- Payload:

```json
{"note_id": "note-..."}
```

- Result output fields: `note.id`, `note.path`, `note.frontmatter`, `note.body`,
  `warnings`, `errors`.

### `kb.note.deprecate`

- 用途：deprecate note 并移动到 deprecated。
- Review gate：需要。
- Payload:

```json
{  "note_id": "note-...",
  "decision": "deprecate",
  "reason": "<non-empty reason>"
}
```

- Result output fields: `note_id`, `path`, `objects.deprecated`, `diffs`,
  `index_rebuild`, `warnings`, `errors`, `next_actions`.

### `kb.index.rebuild`

- 用途：从 object files 重建 derived indexes 并报告 consistency issues。
- Review gate：无。
- Payload:

```json
{  "scope": "all | source | candidate | knowledge | knowledgebase | note | review_queue | tag",
  "object_id": "optional-object-id"
}
```

- Result output fields: `issues`, `index_paths`, `objects.updated`, `diffs`,
  `warnings`, `errors`, `next_actions`.

### `kb.clean.inspect`

- 用途：只读检查 layout/schema drift。
- Review gate：inspect 无；migration execution 需要整批 approval。
- Payload:

```json
{}
```

- Result output fields: `differences`, `migration_required`, `warnings`,
  `errors`, `next_actions`; if migration planning is needed, result status may be
  `needs_llm` and must be resumed according to the returned token.

## Sources And Evidence

- 不要编造 facts、evidence、object IDs 或 source citations。
- Candidate 和 knowledge evidence 必须可追溯到允许的 upstream source objects。
- Evidence item 必须包含 source/object ID、locator，以及 quote、excerpt 或 snippet 之一。
- Notes 不是 candidate creation 的 source evidence。
- Deprecated source 仍保留引用链，但新 candidate 引用 deprecated source 时必须报告 warning 供 review。

## URL And Source-Like Context

- 对 URL source input，将原始 URL 传给 `kb.source.add`；不要在 Claude Code 中 fetch、browse、export、scrape、save 或 retry URL 内容。
- 创建 knowledgebase 时，用户给出的 source/file/directory/URL 只是临时 definition context。
- Knowledgebase create 的 source-like context 不触发 `kb.source.add`，不触发 `kb.candidate.create`，不写入 raw/cleaned source，也不成为 candidate/knowledge evidence。
