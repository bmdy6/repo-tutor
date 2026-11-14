# repo-tutor

**把陌生的 Python 代码库变成带源码出处的新人课程。**

Turn unfamiliar Python repositories into source-linked onboarding courses.

[分步使用](#分步使用) · [配置](#配置) · [MCP 接入](#mcp只读接入) · [Flask 演示](#flask-演示) · [已知限制](#已知限制)

给刚接手 Python 代码库的新人，以及要反复讲解源码的维护者：先看系统做什么、入口在哪里，再沿一次调用理解模块职责。程序按模块和入口可达子图分课，模型写连贯讲解，每个段落保留 `path:line`，并检查漏讲、引用、图节点和源码漂移。

这是 [Flask 3.1.2 第 0 课](examples/flask/lessons/00.md)的真实节选：

> Flask 的核心是一个 WSGI 应用对象：`Flask` 类被文档描述为“实现 WSGI 应用并充当中心对象”，创建后作为视图函数、URL 规则、模板配置等的中央注册表，其构造参数是模块或包名，用于定位资源。`src/flask/app.py:81`

[全局导读与模块地图](examples/flask/lessons/00.md) · [一次请求的分发](examples/flask/lessons/10.md) · [蓝图的记录与注册](examples/flask/lessons/17.md) · [完整大纲](examples/flask/outline.md)

Python 3.11+，macOS / Linux。在已激活的虚拟环境中，从本仓库目录运行这 3 条命令：

```bash
python -m pip install -e .
export REPO_TUTOR_API_KEY='你的 DeepSeek API key'
repo-tutor all /path/to/python-repo --out course
```

打开 `course/lessons/00.md` 开始，再看 `course/outline.md` 和 `course/verification.md`。
只有 `plan`、`write` 和包含它们的 `all` 会发模型请求，源码片段会发送到配置的服务。
默认 DeepSeek，每个输出目录累计上限 20 次（一次命名 + 每课一次，包括第 0 课），失败也计数，不自动重试。
大仓库先 `scan` / `plan` 看课数，按实际课数设置 `max_calls`；超限会停止并保留已有产物。

## 分步使用

```bash
repo-tutor scan /path/to/python-repo --out course
repo-tutor plan /path/to/python-repo --out course
repo-tutor write /path/to/python-repo --out course
repo-tutor verify /path/to/python-repo --out course
```

`scan` 输出 AST 节点、docstring、import/调用/继承关系、入口、未解析调用和文件 SHA256。
JSON Schema 在 [scan.schema.json](src/repo_tutor/scan.schema.json)。`topology.json` 包含依赖顺序、循环依赖组，以及从入口沿静态边得到的有界可达流程。

第 0 课讲系统用途、入口、模块地图和典型调用的生命周期。功能课固定为：2–3 个学习目标 → 按调用顺序的连贯讲解与图 → 关键符号速查表 → 2 道附答案及出处的自测 → 下一课衔接。

分组先按模块聚类，再按最近的路由/协议入口可达子图划分流程；构造器和 CLI 留在模块功能组中。调用和继承边决定课程先后，import 边用于模块地图。环合并为共同先修组，组内用稳定顺序，不声称存在严格先修关系。大组按节点 SCC 单元拆课，`nodes_per_lesson` 是软上限，环不拆。模型只能命名和讲解；节点归属、依赖顺序、阅读路径和图均由程序决定，`plan.json` 可重算校验。

课内的阅读路径从入口出发，按调用位置做 DFS；它是静态阅读辅助，含条件分支，不代表运行轨迹。讲解可选一条代表流程，其余节点放速查表。校验分别统计“讲解段落中出现”“只在速查表出现”和“仅目标/自测/衔接等位置出现”，不会把速查表覆盖当成正文已讲透。

只想先生成部分课文：

```bash
repo-tutor write /path/to/python-repo --out course --lessons 00,01,02
```

未生成的关键节点仍列入漏讲清单。重跑 `all` 复用匹配的大纲，跳过已有课文。第 1 轮 schema v1 计划不能续用，请用新的输出目录重新扫描、规划；修改分组配置也用新目录。

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
| `nodes_per_lesson` | `REPO_TUTOR_NODES_PER_LESSON` | 24，SCC 不拆的软上限 |
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

固定 [pallets/flask 3.1.2](https://github.com/pallets/flask/releases/tag/3.1.2)，24 个生产 Python 文件、439 个节点，包含 348 个关键节点（新增构造与协议入口也纳入覆盖）。
演示把每课软上限设为 48，得到第 0 课 + 20 节功能课；真实调用和机械校验结果见 [演示说明](examples/flask/README.md)。
仓库保留 00、10、17 三课，样例子集和完整课程的校验快照分开记录。完整真实输出保存在演示任务目录，仓库中的速查表覆盖不能代替讲解质量审查。

## 已知限制

- **覆盖完整 ≠ 讲对了。内容正确性需要人看。** 文件、行号、附近符号都有效，也可能配上错误解释。无引用正文检测是启发式，标题、引用块及代码块不做语义事实检查。
- 仅支持 Python AST。不能完整还原动态派发、实例类型、继承方法查找、装饰器运行效果、反射或插件加载；1027 条 Flask 调用表达式未解析，原样保留供人工追查。
- 导入别名在模块内汇总，局部同名遮蔽可能造成误解析；星号导入与完整导出表不支持。入口装饰器按名称启发式识别；WSGI/ASGI 的 `__call__` 按参数名识别，构造入口限名称公开的类。都不证明运行时框架类型或外部可达性。
- 静态可达集合不是运行顺序，调用图也不是运行时追踪。入口遍历默认限制为 100 个节点，结果显式标记是否截断。
- 公开类/函数按名称判定，包含公开方法和 overload 声明；不等同于项目正式 API。模块/入口聚类是结构启发式，不保证完全吻合领域概念；跨模块功能可能需要共同阅读。
- 大文件、解析失败会报告诊断；长函数只给模型有限片段。超上下文时停止。每张流程图最多画前 20 个阅读节点，模块地图显示模块节点。图节点使用扫描身份生成的稳定 ID；自写图也须遵循此格式，未知语法会被保守拒绝。图节点真实不证明边或文字的语义正确。
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

CI 使用 GitHub 托管 Ubuntu（Python 3.11 / 3.13 / 3.14）。本轮账号消费限制使托管任务无法启动，不能视为 CI 通过；本地假模型测试、ruff 和构建已执行。没有注册自托管 runner，仓库保持原可见性。

MIT License。Flask 的许可另见 [FLASK-LICENSE.txt](examples/flask/FLASK-LICENSE.txt)。
