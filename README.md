Turn unfamiliar Python repositories into source-linked onboarding courses.

# repo-tutor

给刚接手 Python 代码库的新人，以及要反复讲解源码的维护者：扫描源码，按静态依赖安排课程，生成带 `path:line` 出处的中文讲解与 Mermaid 图，再检查漏讲节点和无效引用。

Python 3.11+，macOS / Linux。在已激活的虚拟环境中，从本仓库目录运行这 3 条命令：

```bash
python -m pip install -e .
export REPO_TUTOR_API_KEY='你的 DeepSeek API key'
repo-tutor all /path/to/python-repo --out course
```

打开 `course/outline.md`、`course/lessons/` 和 `course/verification.md`。
只有 `plan`、`write` 和包含它们的 `all` 会发模型请求，源码片段会发送到你配置的服务。
默认 DeepSeek；累计请求上限 20，失败也计数，不自动重试。输入项目越大，可能需要减少每课节点数或调整预算。

下面是 [Flask 3.1.2 的真实第 1 课](examples/flask/lessons/01.md)中的一段：

> **Flask.make_shell_context**：它先构造包含 app 和 g 的字典，再依次调用已注册的 shell_context_processors，把每个处理器返回的字典合并进去。这是交互式 shell 中可用变量的来源。`src/flask/app.py:534`

[完整大纲](examples/flask/outline.md) · [第 12 课](examples/flask/lessons/12.md) · [第 14 课](examples/flask/lessons/14.md) · [样例校验报告](examples/flask/verification.md)

## 分步使用

```bash
repo-tutor scan /path/to/python-repo --out course
repo-tutor plan /path/to/python-repo --out course
repo-tutor write /path/to/python-repo --out course
repo-tutor verify /path/to/python-repo --out course
```

`scan` 输出 AST 节点、docstring、import/调用/继承关系、入口、未解析调用和文件 SHA256。
JSON Schema 在 [scan.schema.json](src/repo_tutor/scan.schema.json)。`topology.json` 包含依赖顺序、循环依赖组，以及从入口沿静态边得到的有界可达流程。

课程先讲已解析的依赖，再讲使用者。循环依赖合并成强连通组，组内按稳定 ID 排序；组可能跨课，不能把环内顺序看成严格先修顺序。大纲的节点归属由程序决定，模型只能命名课程和解释代码。

只想先生成部分课文，可以运行 `repo-tutor write /path/to/python-repo --out course --lessons 01,02`。
未生成的关键节点仍会进入漏讲清单。重跑 `all` 会复用匹配的大纲，跳过已有课文；要换课程分组或扫描范围，使用新输出目录。

退出码：`0` 成功，`1` 校验未通过，`2` 输入、配置或生成失败。

## 配置

复制 [repo-tutor.example.toml](repo-tutor.example.toml)，每个子命令都接受 `--config config.toml`。
优先级是 `REPO_TUTOR_*` 环境变量 → 显式 TOML → 默认值。密钥的兜底变量是 `DEEPSEEK_API_KEY`，其次 `OPENAI_API_KEY`；设置通用密钥不会自动切换地址。

| 配置项 | 环境变量 | 默认值 |
| --- | --- | --- |
| `model` | `REPO_TUTOR_MODEL` | `deepseek-chat` |
| `base_url` | `REPO_TUTOR_BASE_URL` | `https://api.deepseek.com/v1` |
| `api_key` | `REPO_TUTOR_API_KEY` | 从兜底变量读取 |
| `max_calls` | `REPO_TUTOR_MAX_CALLS` | 每个输出目录累计 20 次 |
| `nodes_per_lesson` | `REPO_TUTOR_NODES_PER_LESSON` | 24 |
| `excerpt_lines` | `REPO_TUTOR_EXCERPT_LINES` | 45 |
| `max_context_chars` | `REPO_TUTOR_MAX_CONTEXT_CHARS` | 90000 字符 |
| `max_file_bytes` | `REPO_TUTOR_MAX_FILE_BYTES` | 1000000 |
| `citation_proximity` | `REPO_TUTOR_CITATION_PROXIMITY` | 定义行附近 3 行 |

超时、输出 token 上限和目录排除项也在示例配置中。`excludes` 按目录名匹配，环境变量用逗号分隔。
默认排除 tests、docs、examples、虚拟环境和构建目录；符号链接不进入源码扫描，隐藏目录不遍历。
`base_url` 填 API 前缀，程序追加 `/chat/completions`；远端地址要求 HTTPS，本地兼容服务允许 HTTP。
密钥不会写入课程或 `usage.json`，程序也不会自动读取本机密钥仓库。

## MCP：只读接入

安装后启动 `repo-tutor-mcp`，使用 stdio 传输。例如 Codex 配置：

```toml
[mcp_servers.repo_tutor]
command = "/absolute/path/to/venv/bin/repo-tutor-mcp"
```

| 工具 | 输入 | 结果 |
| --- | --- | --- |
| `scan_repository` | `path` | Python AST 清单 |
| `inspect_topology` | `path` | 依赖顺序、环与入口静态流程 |
| `verify_course` | `path`, `lessons_path` | 已有课文的引用与覆盖校验 |

三个工具均标注 `readOnlyHint=true`、`destructiveHint=false`、`openWorldHint=false`。
不调用模型、不写输出文件。已用真实 stdio 客户端验证 initialize、list_tools 和三个工具调用。
MCP 校验针对当前源码；CLI 另有扫描快照漂移检查。此轮未通过 Codex 应用界面做接入验收。

## Flask 演示

固定 [pallets/flask 3.1.2](https://github.com/pallets/flask/releases/tag/3.1.2)，24 个生产 Python 文件、439 个节点，包含 323 个关键节点。
真实全流程生成 14 课，总计 17 次模型调用。请求名是 `deepseek-chat`，API 返回模型名是 `deepseek-flash`；均记录在示例账本中。

完整课程的机械校验：覆盖 323/323，无效引用 0/323。仓库只保留 3 课样例，样例自身覆盖 59/323，其余 264 个节点在 [样例报告](examples/flask/verification.md)中明确列出。
完整 14 课的 [校验快照](examples/flask/full-course-verification.md)与 3 课的校验结果分开放置，复现步骤见 [演示说明](examples/flask/README.md)。

## 已知限制

- **覆盖完整 ≠ 讲对了。内容正确性需要人看。** 文件、行号、附近符号都有效，也可能配上错误解释。无引用正文检测是启发式，标题、引用块及代码块不做语义事实检查。
- 仅支持 Python AST。不能完整还原动态派发、实例类型、继承方法查找、装饰器运行效果、反射或插件加载；1027 条 Flask 调用表达式未解析，原样保留供人工追查。
- 导入别名在模块内汇总，局部同名遮蔽可能造成误解析；星号导入与完整导出表不支持。入口装饰器按名称启发式识别，不校验框架类型。未自动识别 WSGI/ASGI 协议入口。
- 静态可达集合不是运行顺序，调用图也不是运行时追踪。入口遍历默认限制为 100 个节点，结果显式标记是否截断。
- 公开类/函数按名称判定，包含公开方法和 overload 声明；不等同于项目正式 API。第一版课程偏逐符号阅读，尚缺面向新人的全局故事和课程间过渡。
- 大文件、解析失败会报告诊断；长函数只给模型有限片段。超上下文时停止，不会声称完整读懂。
- 依赖 JSON 模式的 OpenAI 兼容 Chat Completions；目前只实测 DeepSeek 和本地假响应。文件锁使用 POSIX，Windows 未适配。
- `path:line` 是相对被扫描仓库的源码定位符，不是本工具仓库内的文件链接；演示可按固定 commit 去原仓库定位。

## 开发与验证

```bash
python -m pip install -e '.[dev]'
pytest -q
ruff check src tests
python -m build
```

fixture 模拟 CLI、路由、相对导入、环和公开/私有符号；只作 AST 输入，不执行其中的假装饰器。
模型生成用假模型测试。架构与失败恢复说明见 [docs/architecture.md](docs/architecture.md)。

CI 默认使用 GitHub 托管 Ubuntu；可临时通过仓库变量 `REPO_TUTOR_RUNNER`（JSON 标签数组）指定自己的 runner。
本轮托管任务因账号计费限制未启动，改用临时 macOS ARM64 self-hosted runner 运行 GitHub Actions；Linux 托管结果仍未验证。

MIT License。Flask 的许可另见 [FLASK-LICENSE.txt](examples/flask/FLASK-LICENSE.txt)。
