# `kb.knowledgebase.map`

## 用途

生成 knowledgebase outline 和 accepted knowledge bindings 的临时 Mermaid map。

## Helper 调用

```bash
python3 /home/sranger/codes/claude-code-marketplace/plugins/kbm/scripts/kbmanager_plugin.py kb.knowledgebase.map '<payload-json>' --pretty
```

## 载荷

```json
{
  "knowledgebase_id": "<optional knowledgebase ID>"
}
```

全局 map 省略 `knowledgebase_id`；不要传空字符串。

## Result 字段

报告 `path`、`markdown`、`issues`、`warnings`、`errors` 和 `next_actions`。

## 硬规则

- 没有 review gate。
- 只生成临时派生 Markdown map，不修改 object facts 或 repo-tracked indexes。
- 如果有 invalid `bindto`、missing outline nodes 或 unbound knowledge，展示 issues 并建议 check。
