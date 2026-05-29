# `kb.index.rebuild`

## 用途

从 object files 重建 derived indexes，并报告一致性问题。

## Helper 调用

```bash
python3 /home/sranger/codes/claude-code-marketplace/plugins/kbm/scripts/kbmanager_plugin.py kb.index.rebuild '{}' --pretty
```

## 载荷

```json
{}
```

## Result 字段

报告 updated index paths、`issues`、invalid `bindto`、missing outline nodes、`warnings`、`errors` 和 `next_actions`。

## 硬规则

- 只通过 `kb.index.rebuild` 写 index files。
- 不要从 check 自动修复 object files。
- Indexes 是派生文件，不是 object facts。
