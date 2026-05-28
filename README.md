# 个人 AI 中台

一个纯 Markdown/PDF/YAML 文件系统版的个人 AI 知识中台。

KBManager 不依赖数据库、RAG、向量库或全文搜索服务。用户在自己的 git
工作区中使用 KBManager，所有 source、note、candidate、knowledge、
knowledgebase、索引和输入内容都属于该用户工作区。

KBManager ships as a Claude Code plugin named `kbm`. The plugin provides
`kbm-*` skills and an internal JSON helper for calling the packaged `kb.*` API.
It does not expose Claude Code commands.

## 文档

- [架构设计](docs/架构设计.md)：设计原则、架构分层、单入口编排、目录结构和 LLM 边界。
- [对象](docs/对象.md)：source、candidate、knowledge、knowledgebase、note、index、prompt 等对象结构。
- [Interface](docs/Interface.md)：第一层交互接口、skills、输入输出和 review 交互。
- [API 设计](docs/API设计.md)：第二层 Application API、原子接口、review gate 和 API 侧 LLM prompt 组装。
- [API 流程图](docs/流程图.md)：第二层 `kb.*` API 的执行流程和数据影响。
- [Claude Code Plugin](docs/ClaudePlugin.md)：插件结构、安装、更新、卸载、权限和数据边界。
