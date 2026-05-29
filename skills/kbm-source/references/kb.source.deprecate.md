# `kb.source.deprecate`

## 用途

将 source 标记为 deprecated，并保留历史引用链。

## Helper 调用

```bash
python3 /home/sranger/codes/claude-code-marketplace/plugins/kbm/scripts/kbmanager_plugin.py kb.source.deprecate /path/to/payload.json --pretty
```

## 载荷

```json
{
  "source_id": "source-...",
  "reason": "<non-empty reason>"
}
```

必填字段：`source_id`、`reason`。

## Result 字段

报告 `source_id`、`impacts`、`objects.deprecated`、`diffs`、`index_rebuild`、`warnings`、`errors` 和 `next_actions`。

## 硬规则

- 最终写入会由 Claude Code PreToolUse hook 触发审批；用户意图明确时不要额外要求一次确认。
- 不要直接编辑 source metadata。
- 不要物理删除 source。
