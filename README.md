# 个人 AI 中台

一个纯 Markdown/PDF/HTML/YAML 文件系统版的个人 AI 知识中台。

本项目不依赖数据库、RAG、向量库或全文搜索服务，目标是提供一个不携带用户数据的知识中台。用户在自己的 git 工作区中使用 KBManager，所有 source、note、knowledge、索引和输入内容都属于该用户工作区，并可由 Claude Code 通过分层 API 按明确规则协作维护。

KBManager also ships as a Claude Code plugin. The plugin exposes namespaced
commands such as `/kbm:init` and `/kbm:source-add`, while user
knowledge data stays in the user's workspace and is not packaged with the
plugin.

## 文档

- [架构设计](docs/架构设计.md)：设计原则、架构分层、目录结构和 LLM 参与边界。
- [对象](docs/对象.md)：source、candidate、knowledge、knowledge base、note、index、prompt 等对象结构。
- [Interface](docs/Interface.md)：第一层交互接口、输入输出、slash command、LLM prompt 组装和 review 交互。
- [API 设计](docs/API设计.md)：第二层 Application API、原子接口、review gate 和 API 侧 LLM prompt 组装。
- [API 流程图](docs/流程图.md)：第二层 `kb.*` API 的执行流程和数据影响。
- [Slash Command 流程图](docs/SlashCommand流程图.md)：第一层 slash command 的交互流程，展示到调用 API 为止。
- [Claude Code Plugin](docs/ClaudePlugin.md)：插件结构、安装、更新、卸载和数据边界。
