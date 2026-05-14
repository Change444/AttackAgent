# AttackAgent 用户操作手册

## 1. 系统概述

AttackAgent 是面向授权靶场和 CTF 竞赛的渗透测试 Agent。核心设计理念：**约束推理而非候选选择**——框架引导模型决策，不限制创造力。

### 双路径架构

系统采用结构化路径（APGPlanner）和自由探索路径的**双路径架构**：

| 模型模式 | 结构化路径 | 自由探索路径 |
|----------|-----------|-------------|
| `model=None`（纯规则） | HeuristicReasoner + APGPlanner | HeuristicFreeExplorationPlanner |
| `model=openai/anthropic` | LLMReasoner + APGPlanner | ConstraintAwareReasoner |

`PathSelectionStrategy` 根据置信度和复杂度动态选择路径，`switch_path()` 在停滞或预算耗尽时自动切换。

### 当前解题能力

- 解题率约 25-30%（已可连接真实 CTFd 靶场）
- 9 个执行原语覆盖 HTTP、浏览器、文件、二进制、沙箱等场景
- 14 个模式族覆盖主流 CTF 类别
- 关键限制见第 8 节

---

## 2. 安装与依赖

### 基础要求

- Python 3.10+
- 无外部依赖即可运行纯规则模式

### 可选依赖组

按需安装增强功能：

| 功能 | 安装命令 | 说明 |
|------|---------|------|
| OpenAI LLM | `pip install attack-agent[openai]` | openai >= 1.0 |
| Anthropic LLM | `pip install attack-agent[anthropic]` | anthropic >= 0.20 |
| HTTP 增强 | `pip install attack-agent[http]` | requests >= 2.28，multipart + auth |
| Playwright 浏览器 | `pip install attack-agent[browser]` | playwright >= 1.40，JS 渲染 |
| 语义检索 | `pip install attack-agent[embeddings]` | sentence-transformers >= 2.2 |
| 全功能 | `pip install attack-agent[all]` | 以上所有 |
| Team Runtime CLI + API | `pip install attack-agent[team]` | fastapi + uvicorn + httpx + click + rich |
| 仅 Team CLI | `pip install attack-agent[cli]` | click + rich |
| 仅 Team API | `pip install attack-agent[api]` | fastapi + uvicorn + httpx |

Playwright 安装后需额外下载浏览器：

```bash
pip install attack-agent[browser]
playwright install chromium
```

---

## 3. 快速开始（纯规则模式）

无需 LLM 和外部依赖，直接运行：

```bash
python -m attack_agent --config config/settings.json
```

默认使用 InMemoryCompetitionProvider 和一个本地 demo 挑战。输出解题统计：

```
AttackAgent starting...
Result: 1/1 challenges solved.
```

### Python API

```python
from attack_agent.factory import build_team_runtime
from attack_agent.provider import InMemoryCompetitionProvider
from attack_agent.platform_models import ChallengeDefinition

provider = InMemoryCompetitionProvider([
    ChallengeDefinition(
        id="test-1",
        name="Test Challenge",
        category="web",
        difficulty="easy",
        target="http://127.0.0.1:8000",
        description="A simple web challenge.",
        metadata={"flag": "flag{test123}", "hint": "Look at the login page."},
    ),
])
runtime = build_team_runtime(provider)
runtime.solve_all()
```

---

## 4. 接入 LLM 模型

系统支持 OpenAI 和 Anthropic 两种 LLM 提供商，接入后切换为 LLM 双路径（LLMReasoner + ConstraintAwareReasoner）。

### 4.1 OpenAI

**方式一：CLI 参数（推荐）**

```bash
export OPENAI_API_KEY="sk-..."
python -m attack_agent --model openai --verbose
```

**方式二：配置文件**

编辑 `config/settings.json`：

```json
{
  "model": {
    "provider": "openai",
    "model_name": "gpt-4o",
    "api_key_env": "OPENAI_API_KEY",
    "temperature": 0.3,
    "max_tokens": 1024
  }
}
```

然后运行：

```bash
python -m attack_agent --config config/settings.json --verbose
```

**自定义端点**（代理/Azure/本地推理服务器）：

```json
{
  "model": {
    "provider": "openai",
    "base_url": "https://your-proxy.example.com/v1",
    "api_key_env": "OPENAI_API_KEY"
  }
}
```

### 4.3 外部模型 / 自定义网关

AttackAgent 支持通过 OpenAI SDK 连接任何 OpenAI 兼容的外部模型网关（企业内网网关、国产大模型代理、本地推理服务器等）。只需设置 `base_url` 和对应的 `model_name` 即可。

**典型配置**（以企业网关为例）：

```json
{
  "model": {
    "provider": "openai",
    "model_name": "glm-4",
    "base_url": "https://aigw.inone.nsfocus.com/glm/v1",
    "api_key_env": "NSFOCUS_API_KEY"
  }
}
```

运行：

```bash
# 设置 API Key（变量名与 api_key_env 对应）
export NSFOCUS_API_KEY="你的密钥"

python -m attack_agent --config config/settings.json --verbose
```

**要点**：

| 项 | 说明 |
|---|------|
| `provider` | 始终用 `"openai"`（外部网关走 OpenAI SDK，与 Anthropic SDK 不兼容） |
| `model_name` | 填网关支持的模型 ID（如 `glm-4`、`glm-4-flash`、`qwen-plus` 等），默认 `gpt-4o` 对外部网关无效 |
| `base_url` | 网关地址，需包含 `/v1` 路径（SDK 自动拼接 `/chat/completions`） |
| `api_key_env` | 自定义环境变量名，不必是 `OPENAI_API_KEY` |
| SSL | 如果网关使用自签名证书，需同时设置 `http.verify_ssl: false` |
| 依赖 | 仍需安装 `pip install attack-agent[openai]`（SDK 作为 HTTP 客户端） |

**其他常见网关示例**：

```json
// 本地 vLLM 推理服务器
{
  "model": {
    "provider": "openai",
    "model_name": "Qwen2.5-72B-Instruct",
    "base_url": "http://localhost:8000/v1",
    "api_key": "token-placeholder"
  }
}

// Azure OpenAI
{
  "model": {
    "provider": "openai",
    "model_name": "gpt-4o",
    "base_url": "https://your-resource.openai.azure.com/openai/deployments/your-deployment",
    "api_key_env": "AZURE_OPENAI_API_KEY"
  }
}

// OneAPI / New API 等多模型代理
{
  "model": {
    "provider": "openai",
    "model_name": "deepseek-chat",
    "base_url": "https://your-oneapi.example.com/v1",
    "api_key_env": "ONEAPI_KEY"
  }
}
```

> **注意**：外部模型必须在 `response_format={"type": "json_object"}` 模式下输出有效 JSON。如果不支持该模式，可将 `max_tokens` 适当调大并依赖内置的 `_extract_json_from_text` 三级 JSON 解析器（直接解析 → markdown code block → 嵌套花括号提取）作为兜底。

### 4.4 Anthropic

与 OpenAI 同理，默认模型为 `claude-sonnet-4-20250514`：

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
python -m attack_agent --model anthropic --verbose
```

配置文件方式：

```json
{
  "model": {
    "provider": "anthropic",
    "model_name": "claude-sonnet-4-20250514",
    "api_key_env": "ANTHROPIC_API_KEY"
  }
}
```

#### Thinking Model 支持

Anthropic 适配器支持 extended thinking（推理模型先进行内部推理再输出 JSON）。启用后可提升复杂推理质量，但需要注意：

- **配置字段**：`enable_thinking: true`
- **budget_tokens**：自动计算为 `min(max_tokens // 3, 2048)`
- **temperature**：thinking 启用时 SDK 强制要求 `temperature=1`
- **自动回退**：如果 thinking 消耗了全部 output budget（无 text 输出），适配器会自动去掉 thinking 参数重新请求

配置示例（Xiaomi mimo-v2.5-pro）：

```json
{
  "model": {
    "provider": "anthropic",
    "model_name": "mimo-v2.5-pro",
    "api_key": "your-api-key",
    "base_url": "https://token-plan-cn.xiaomimimo.com/anthropic",
    "max_tokens": 8192,
    "enable_thinking": true
  }
}
```

> **注意**：thinking 模型会增加 API 响应延迟（budget_tokens 越大延迟越高）。建议 `max_tokens` 至少 4096 以留足 text 输出空间。如果频繁出现"thinking consumed output budget"回退，可适当增大 `max_tokens`。

> **环境变量冲突**：Anthropic SDK 自动读取 `ANTHROPIC_API_KEY`、`ANTHROPIC_AUTH_TOKEN`、`ANTHROPIC_BASE_URL` 环境变量。如果这些变量残留旧值，可能与配置文件中的 `api_key`/`base_url` 冲突导致 401 错误。适配器会在初始化时自动清除这些环境变量，但如果手动设置过请确保值正确。

### 4.5 API Key 设置

三种方式（优先级从高到低）：

| 方式 | 配置字段 | 说明 |
|------|---------|------|
| 环境变量 | `api_key_env` | 如 `"OPENAI_API_KEY"`，读取对应环境变量 |
| 配置文件直填 | `api_key` | 明文写入 settings.json（不推荐） |
| CLI 无直接参数 | — | 需通过配置文件或环境变量 |

**推荐使用环境变量**，避免密钥泄露：

```bash
# Linux/Mac
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."

# Windows PowerShell
$env:OPENAI_API_KEY = "sk-..."
$env:ANTHROPIC_API_KEY = "sk-ant-..."
```

### 4.6 ModelConfig 完整字段

| 字段 | 默认值 | 说明 |
|------|-------|------|
| `provider` | `"heuristic"` | `"heuristic"` / `"openai"` / `"anthropic"` |
| `model_name` | `""` | 模型 ID，OpenAI 默认 `gpt-4o`，Anthropic 默认 `claude-sonnet-4-20250514` |
| `api_key` | `""` | 明文 API Key（不推荐） |
| `api_key_env` | `""` | 环境变量名，如 `"OPENAI_API_KEY"` |
| `base_url` | `""` | 自定义端点 URL |
| `temperature` | `0.3` | 生成温度 |
| `max_tokens` | `1024` | 最大生成 token 数 |
| `timeout_seconds` | `30` | 单次请求超时 |
| `max_retries` | `2` | 限流/连接错误最大重试次数 |
| `observation_summary_budget_chars` | `2000` | LLM 上下文中观测摘要的字符预算 |
| `enable_thinking` | `false` | Anthropic thinking model 开关（启用后 budget_tokens=min(max_tokens//3,2048)） |

---

## 5. 连接靶场

三种靶场连接方式（优先级从高到低）：CTFd → HTTP → InMemory。

### 5.1 CTFd 靶场（真实 CTF 竞赛）

**Session 认证**（用户名 + 密码）：

```bash
python -m attack_agent \
  --ctfd-url https://ctf.example.com \
  --ctfd-username myuser \
  --ctfd-password mypass \
  --model openai --verbose
```

**API Token 认证**（Bearer）：

```bash
python -m attack_agent \
  --ctfd-url https://ctf.example.com \
  --ctfd-token "your_api_token" \
  --model openai --verbose
```

CTFd 提供商自动映射 API：
- 拉取题目列表：`GET /api/v1/challenges`
- 提交 flag：`POST /api/v1/challenges/attempt`

### 5.2 HTTP 靶场（自定义 REST API）

适用于自有靶场平台，需实现以下 API：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/challenges` | GET | 返回题目列表 |
| `/start_challenge` | POST | 启动题目实例 |
| `/stop_challenge` | POST | 停止实例 |
| `/submit` | POST | 提交 flag |
| `/hint` | POST | 获取提示 |
| `/status/{instance_id}` | GET | 查询实例状态 |

运行：

```bash
python -m attack_agent --provider-url http://127.0.0.1:8080 --model openai --verbose
```

### 5.3 InMemory 模式（本地测试/演示）

通过 JSON 文件加载题目：

```bash
python -m attack_agent --challenges-file my_challenges.json
```

题目 JSON 格式：

```json
[
  {
    "id": "web-1",
    "name": "Simple SQLi",
    "category": "web",
    "difficulty": "easy",
    "target": "http://127.0.0.1:8000",
    "description": "A login page with SQL injection vulnerability.",
    "flag_pattern": "flag\\{[^}]+\\}",
    "metadata": {
      "flag": "flag{sqli_bypass_123}",
      "hint": "Try admin' OR '1'='1 on the login form.",
      "hint_budget": 2
    }
  }
]
```

### 5.4 题目定义字段说明

| 字段 | 必填 | 默认值 | 说明 |
|------|------|-------|------|
| `id` | 是 | — | 题目唯一标识 |
| `name` | 是 | — | 题目名称 |
| `category` | 是 | — | 分类（web/crypto/pwn/reverse/misc 等） |
| `difficulty` | 是 | — | 难度 |
| `target` | 是 | — | 目标 URL 或主机 |
| `description` | 否 | `""` | 题目描述 |
| `flag_pattern` | 否 | `flag\{[^}]+\}` | flag 正则匹配模式 |
| `metadata` | 否 | `{}` | 额外信息（flag、hint、hint_budget 等） |

### 5.5 本地靶场测试

项目自带本地靶场服务器，包含 4 个 CTF 挑战（2 easy + 2 medium），可用于快速验证解题能力：

```bash
# 启动靶场服务器
python scripts/local_range.py
# 或指定端口
python scripts/local_range.py --port 9999
```

| 题目 ID | 名称 | 难度 | 测试原语 |
|---------|------|------|---------|
| web-auth-easy | Login Portal | easy | session-materialize + http-request |
| web-render-easy | Hidden Comments | easy | browser-inspect（HTML 注释提取） |
| web-encoding-medium | Base64 Cookie | medium | http-request + code-sandbox（base64） |
| web-chain-medium | Multi-Step API | medium | http-request chain + structured-parse |

靶场实现完整的 CompetitionProvider REST API（`/challenges`、`/start_challenge`、`/submit`、`/hint`），同时在同一端口上提供挑战页面。浏览器访问 `http://127.0.0.1:8484` 可查看所有题目。

运行 AttackAgent 对接本地靶场：

```bash
# 纯规则模式
python -m attack_agent --provider-url http://127.0.0.1:8484 --verbose

# LLM 模式
python -m attack_agent --config config/local-openai-compatible.json --provider-url http://127.0.0.1:8484 --verbose
```

---

## 6. 配置详解

所有配置通过 `config/settings.json` 管理，CLI 参数可覆盖部分字段。

### 6.1 platform（控制层）

| 字段 | 默认值 | 说明 |
|------|-------|------|
| `max_cycles` | `50` | 每题最大解题循环数 |
| `timeout_seconds` | `300` | 单题超时（秒） |
| `enable_auto_submit` | `true` | 自动提交 flag |
| `stagnation_threshold` | `8` | 停滞超过此阈值则放弃 |
| `flag_confidence_threshold` | `0.6` | flag 置信度低于此值不提交 |

### 6.2 dual_path（双路径规划）

| 字段 | 默认值 | 说明 |
|------|-------|------|
| `structured_path_weight` | `0.7` | 结构化路径权重 |
| `free_exploration_weight` | `0.3` | 自由探索路径权重 |
| `max_exploration_attempts` | `5` | 最大探索尝试次数 |
| `exploration_budget_per_project` | `3` | 每题自由探索预算 |
| `enable_pattern_discovery` | `true` | 启用模式发现 |
| `enable_semantic_retrieval` | `true` | 启用语义检索 |

### 6.3 security（安全壳）

| 字段 | 默认值 | 说明 |
|------|-------|------|
| `allowed_hostpatterns` | `["127.0.0.1", "localhost"]` | 目标域名白名单 |
| `max_http_requests` | `30` | 单题最大 HTTP 请求数 |
| `max_sandbox_executions` | `5` | 单题最大沙箱执行数 |
| `max_program_steps` | `15` | 单计划最大步骤数 |
| `require_observation_before_action` | `true` | 必须先观察再操作 |
| `max_estimated_cost` | `50.0` | 最大估算成本 |

**重要：** 连接外部靶场时必须将目标域名加入 `allowed_hostpatterns`，否则安全壳会阻止执行。

### 6.4 browser（浏览器引擎）

| 字段 | 默认值 | 说明 |
|------|-------|------|
| `engine` | `"auto"` | `"auto"` / `"playwright"` / `"stdlib"` |
| `headless` | `true` | 无头模式 |
| `browser_type` | `"chromium"` | `"chromium"` / `"firefox"` / `"webkit"` |
| `timeout_seconds` | `30.0` | 页面加载超时 |
| `extract_scripts` | `true` | 提取页面 JS |

### 6.5 http（HTTP引擎）

| 字段 | 默认值 | 说明 |
|------|-------|------|
| `engine` | `"auto"` | `"auto"` / `"requests"` / `"stdlib"` |
| `verify_ssl` | `true` | SSL 证书验证（`false` 允许自签名） |
| `max_redirects` | `10` | 最大重定向次数 |
| `timeout_seconds` | `10.0` | 请求超时 |

### 6.6 关键参数调节建议

| 场景 | 建议 |
|------|------|
| 目标站点响应慢 | 提高 `http.timeout_seconds` 和 `platform.timeout_seconds` |
| flag 格式非 `flag{...}` | 修改 `flag_pattern`，如 `ctf\{[^}]+\}` 或 `[A-Z0-9]{32}` |
| 连接外部靶场 | 添加域名到 `security.allowed_hostpatterns` |
| 降低提交门槛 | 降低 `flag_confidence_threshold`（如 0.4） |
| 提高解题耐心 | 提高 `stagnation_threshold`（如 12）和 `max_cycles`（如 80） |
| 自签名证书靶场 | 设置 `http.verify_ssl: false` |

### 6.7 CLI 覆盖参数

| CLI 参数 | 对应配置字段 |
|----------|------------|
| `--model` | `model.provider` |
| `--max-cycles` | `platform.max_cycles` |
| `--stagnation-threshold` | `platform.stagnation_threshold` |
| `--confidence-threshold` | `platform.flag_confidence_threshold` |

示例：

```bash
python -m attack_agent --model openai --max-cycles 80 --stagnation-threshold 12 --verbose
```

---

## 7. 运行输出与状态理解

### 7.1 解题阶段

每道题经历 6 个阶段的状态机：

| 阶段 | 含义 | 下一阶段 |
|------|------|---------|
| **BOOTSTRAP** | 题目已加载，未创建实例 | → REASON |
| **REASON** | 实例已启动，选择 WorkerProfile | → EXPLORE |
| **EXPLORE** | 执行攻击计划，收集观测和 flag | → CONVERGE 或循环 |
| **CONVERGE** | 候选 flag 已收集，等待提交 | → DONE 或 ABANDONED |
| **DONE** | flag 已接受，题目解决 | 终态 |
| **ABANDONED** | 停滞超阈值，放弃解题 | 终态 |

### 7.2 --verbose 输出

添加 `--verbose` 后输出详细信息：

- **Run journal**：每题的完整事件日志（观测、行动、结果）
- **Pattern graph**：模式图节点和边的关系

### 7.3 9 个原语

| # | 原语 | 能力 | 用途 |
|---|------|------|------|
| 1 | `http-request` | network/http | HTTP 请求（GET/POST/PUT/DELETE），支持 headers、auth、JSON/form body、文件上传 |
| 2 | `browser-inspect` | browser/dom | 抓取和解析 HTML 页面，提取链接、表单、脚本、注释 |
| 3 | `session-materialize` | session/state | 登录/会话建立，CSRF 预取，auth token 持久化 |
| 4 | `artifact-scan` | artifact/fs | 文件扫描，ZIP/tar 解压提取，内容预览 |
| 5 | `structured-parse` | text/parse | 解析 JSON/HTML/headers 观测结果 |
| 6 | `diff-compare` | compare/diff | 对比两个观测的差异 |
| 7 | `code-sandbox` | sandbox/transform | 安全沙箱执行 Python（hashlib/base64/zlib/csv 等） |
| 8 | `binary-inspect` | binary/strings | 二进制字符串提取，ELF/PE 头解析 |
| 9 | `extract-candidate` | extract/flag | 扫描所有观测寻找 flag 模式匹配 |

### 7.4 WorkerProfile

不同题目类型自动选择不同的 WorkerProfile，决定可用原语集合：

| Profile | 可用原语 |
|---------|---------|
| NETWORK | http-request, session-materialize, structured-parse, diff-compare, code-sandbox, extract-candidate |
| BROWSER | http-request, browser-inspect, structured-parse, diff-compare, code-sandbox, extract-candidate |
| ARTIFACT | artifact-scan, structured-parse, code-sandbox, extract-candidate |
| BINARY | binary-inspect, structured-parse, code-sandbox, extract-candidate |
| SOLVER | structured-parse, diff-compare, code-sandbox, extract-candidate |
| HYBRID | 全部 9 个 |

---

## 8. 常见问题与排查

### SDK 未安装

```
Error: openai SDK not installed. Run: pip install attack-agent[openai]
```

解决：按提示安装对应依赖组。

### API Key 未设置

```
ValueError: API key not found: neither api_key nor api_key_env provided
```

解决：设置环境变量或配置文件中的 `api_key_env`/`api_key`。

### 安全壳阻止执行

```
SecurityShell: critical violation — target host not in allowed patterns
```

解决：将目标域名加入 `config/settings.json` 的 `security.allowed_hostpatterns`：

```json
{
  "security": {
    "allowed_hostpatterns": ["127.0.0.1", "localhost", "ctf.example.com"]
  }
}
```

### Flag 置信度不足未提交

系统默认置信度门槛 0.6。如果 flag 格式正确但未提交，降低门槛：

```bash
python -m attack_agent --confidence-threshold 0.4 --verbose
```

### Windows 终端 UnicodeEncodeError

Windows PowerShell 默认使用 GBK 编码，LLM 返回文本可能包含 GBK 无法编码的字符。系统内置 `_safe_print()` 自动处理此问题（替换不可编码字符），无需手动干预。

### Anthropic 环境变量冲突 401

如果系统环境变量 `ANTHROPIC_API_KEY`、`ANTHROPIC_AUTH_TOKEN` 或 `ANTHROPIC_BASE_URL` 残留旧值，Anthropic SDK 会自动读取并添加冲突的 Bearer header，导致 401 Unauthorized。适配器在初始化时自动清除这些环境变量。如果仍有问题，手动清除：

```bash
# Linux/Mac
unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL

# Windows PowerShell
Remove-Item Env:\ANTHROPIC_API_KEY
Remove-Item Env:\ANTHROPIC_AUTH_TOKEN
Remove-Item Env:\ANTHROPIC_BASE_URL
```

### Thinking model 无 text 输出

某些 thinking 模型（如 mimo-v2.5-pro）可能消耗全部 output budget 于 thinking，不产生 text block。适配器自动 re-request（去掉 thinking 参数）获取 JSON 输出。如果频繁触发回退，增大 `max_tokens`：

```json
{
  "model": {
    "max_tokens": 8192,
    "enable_thinking": true
  }
}
```

### code-sandbox RuntimeError

LLM 生成的代码可能使用不允许的 Python 语法（如 `lambda`、`global`、`async`）。系统自动捕获 RuntimeError 并返回 `_clean_fail("code-sandbox")`，不会崩溃。可在 verbose 日志中查看具体失败原因。

### 解题率低的原因分析

| 问题 | 影响 | 当前状态 |
|------|------|---------|
| browser-inspect 不执行 JS | Web 题 70% 不能解 | Playwright 可用但默认 stdlib 回退 |
| session-materialize 无多步认证 | 需多步登录的题不能解 | 单步 CSRF + auth 持久化已实现 |
| code-sandbox 禁止 lambda | 无法用 lambda 表达式 | class/with/raise + zlib/csv 已放开 |
| 无 crypto 库 | 高级密码题不能解 | hashlib/base64 可用，pycryptodome 未接入 |
| 14 族关键词覆盖 | 主流 CTF 类别已覆盖 | SSRF/SSTI/CSRF/IDOR/crypto/pwn/protocol/race 已加入 |

---

## 9. Python API 进阶用法

### 9.1 直接使用 TeamRuntime

```python
from attack_agent.factory import build_team_runtime
from attack_agent.provider import InMemoryCompetitionProvider
from attack_agent.platform_models import ChallengeDefinition
from attack_agent.config import AttackAgentConfig

challenges = [
    ChallengeDefinition(
        id="crypto-1",
        name="Base64 Decode",
        category="crypto",
        difficulty="easy",
        target="http://127.0.0.1:8000/crypto",
        description="Decode the hidden message.",
        metadata={"flag": "flag{base64_is_easy}", "hint": "The message is base64-encoded."},
    ),
]

config = AttackAgentConfig.from_defaults()
provider = InMemoryCompetitionProvider(challenges)
runtime = build_team_runtime(provider, agent_config=config)
runtime.solve_all()
```

### 9.2 接入 LLM 的 Python API

```python
from attack_agent.model_adapter import build_model_from_config
from attack_agent.config import AttackAgentConfig, ModelConfig

config = AttackAgentConfig.from_defaults()
config.model = ModelConfig(
    provider="openai",
    model_name="gpt-4o",
    api_key_env="OPENAI_API_KEY",
)

model = build_model_from_config(config.model)
runtime = build_team_runtime(provider, model=model, agent_config=config)
runtime.solve_all()
```

### 9.3 自定义 Provider

实现 `CompetitionProvider` 协议的 6 个方法即可：

```python
from attack_agent.platform_models import (
    ChallengeDefinition, ChallengeInstance, SubmissionResult, HintResult
)

class MyProvider:
    def list_challenges(self) -> list[ChallengeDefinition]:
        ...  # 从你的靶场拉取题目

    def start_challenge(self, challenge_id: str) -> ChallengeInstance:
        ...  # 启动题目实例

    def stop_challenge(self, instance_id: str) -> bool:
        ...  # 停止实例

    def submit_flag(self, instance_id: str, flag: str) -> SubmissionResult:
        ...  # 提交 flag

    def request_hint(self, challenge_id=None, instance_id=None) -> HintResult:
        ...  # 获取提示

    def get_instance_status(self, instance_id: str) -> str:
        ...  # 查询实例状态
```

### 9.4 自定义 Reasoner

```python
from attack_agent.reasoning import HeuristicReasoner
from attack_agent.platform_models import WorkerProfile

class MyReasoner(HeuristicReasoner):
    def choose_profile(self, challenge, allowed_profiles):
        # 自定义 WorkerProfile 选择逻辑
        if challenge.category == "crypto":
            return WorkerProfile.SOLVER
        return super().choose_profile(challenge, allowed_profiles)

runtime = build_team_runtime(provider, reasoner=MyReasoner(), agent_config=config)
```

### 9.5 运行测试

```bash
# 全量测试
python -m unittest discover tests/

# 单个测试文件
python -m unittest tests/test_platform_flow.py

# 指定测试方法
python -m unittest tests/test_real_primitives.TestRealPrimitives.test_http_post
```

---

## 10. Team Runtime

AttackAgent 提供 Team Runtime 多 Solver 协作平台。L1-L11 平台组件已经存在，L11 稳定化已完成：所有 Manager 决策记录为 STRATEGY_ACTION、批准的提交仅执行一次、暂停/恢复阻断调度循环、验证状态字段对齐、ToolBroker 真实路径事件日志、Observer 触发/节流、run_id 隔离回放。当前支持 CLI、Python API、REST API + SSE 事件流、Web UI Console 四种操作面。

详细使用说明见 [docs/TEAM_PLATFORM_GUIDE.md](TEAM_PLATFORM_GUIDE.md)。

### 10.1 L1-L11 能力栈

| Phase | 能力 | 说明 |
|-------|------|------|
| L1 | 事件语义 | IDEA_PROPOSED/CLAIMED/VERIFIED/FAILED, CANDIDATE_FLAG, STRATEGY_ACTION |
| L2 | Manager 上下文 | 每次决策前编译 ManagerContext（想法、记忆、Solver 状态、政策约束） |
| L3 | Policy/Review 执行门控 | deny→无记录, needs_review→创建 review+不执行, approve→执行一次 |
| L4 | 记忆驱动 Solver 连续性 | SolverContextPack, MemoryReducer, 失败边界防止重复尝试 |
| L5 | SolverSession 生命周期 | created→assigned→running→completed/failed, idea 独占租约 |
| L6 | KnowledgePacket + MergeHub | 结构化 Solver 协作：validate→dedup→arbitrate→route |
| L7 | Observer 调度循环 | 干预级别：observe/reminder/steer/throttle/stop_reassign/safety_block |
| L8 | ToolBroker 实执行路径 | 9 个原语全部 brokered, IO 依赖原语走 IOContextProvider, 真实路径 retroactive 事件 |
| L9 | REST API + SSE 事件流 | 29 端点 + 实时 SSE 推送 + 项目生命周期 |
| L10 | Web UI Console | 11 视图 + 人工操作 + SSE 实时更新 |
| L11 | 真实路径稳定化 | STRATEGY_ACTION 分离、批准提交一次执行、暂停恢复阻断、验证字段对齐、ToolBroker retroactive 日志、Observer 触发节流、run_id 隔离 |

### 10.2 快速上手

```bash
# 安装
pip install -e ".[team]"

# CLI 查看项目状态
python -m attack_agent team status

# 启动 HTTP API（同时提供 Web UI）
python -m attack_agent team serve --port 8000

# Python API
from attack_agent.team.runtime import TeamRuntime
runtime = TeamRuntime()
project = runtime.run_project("web-auth-easy")
report = runtime.get_status(project.project_id)
runtime.close()
```

### 10.3 CLI 命令

```bash
# 项目管理
python -m attack_agent team run --config config/team_settings.json
python -m attack_agent team status
python -m attack_agent team status <project_id>

# 回放
python -m attack_agent team replay <project_id>
python -m attack_agent team replay-steps <project_id>

# Review 操作
python -m attack_agent team reviews
python -m attack_agent team reviews <project_id>
python -m attack_agent team review approve <request_id> --project-id <pid> --reason "approved"
python -m attack_agent team review reject <request_id> --project-id <pid> --reason "rejected"
python -m attack_agent team review modify <request_id> --project-id <pid> --reason "modified"

# 观察与评估
python -m attack_agent team observe <project_id>
python -m attack_agent team evaluate <project_id>
python -m attack_agent team tools

# API 服务器
python -m attack_agent team serve --port 8000
```

---

## 11. Web UI Console

L10 实现的 Web UI 提供 SOC 风格深色主题操作界面，所有数据通过 L9 REST API 和 SSE 事件流获取，不直接访问 Blackboard。

### 11.1 启动

**生产模式**（单端口，API + UI 一体）：

```bash
cd web && npm install && npm run build   # 构建前端
python -m attack_agent team serve --port 8000   # 后端自动挂载 web/dist/
```

浏览器访问：`http://localhost:8000`

**开发模式**（热重载，前后端分离）：

```bash
# 终端 1：后端
python -m attack_agent team serve --port 8000

# 终端 2：前端（Vite dev server，/api 代理到 8000）
cd web && npm install && npm run dev   # http://localhost:5173
```

浏览器访问：`http://localhost:5173`（推荐开发使用）

### 11.2 11 个核心视图

| 视图 | 路由 | 说明 |
|------|------|------|
| Dashboard | `/dashboard` | 项目列表 + 全局统计（Solver 数、想法数、事实数、Review 数、候选 flag） |
| Project Workspace | `/projects/{id}` | 项目详情 + 生命周期控制 + 标签页（想法/记忆/Solver/Review） |
| Graph View | `/projects/{id}/graph` | 物化状态：事实节点、想法节点、Solver 节点、Packet 节点 |
| Team Board | `/projects/{id}/team` | Solver 池 + 状态徽章 + 预算进度条 |
| Idea Board | `/projects/{id}/ideas` | 想法生命周期列：pending→claimed→testing→verified→failed→shelved |
| Memory Board | `/projects/{id}/memory` | 记忆条目按类型过滤（fact/credential/endpoint/boundary/hint/session） |
| Observer Panel | `/projects/{id}/observer` | 观察报告 + 严重级别 + 干预级别徽章 |
| Review Queue | `/reviews` | 全局 Review 队列 + approve/reject 按钮 + 因果链 |
| Candidate Flag Panel | `/projects/{id}/flags` | 候选 flag + 证据链 |
| Artifact Viewer | `/projects/{id}/artifacts` | Artifact 列表 |
| Replay Timeline | `/projects/{id}/replay` | 步骤回放 + 解释 + 状态快照 |

### 11.3 人工操作

| 操作 | 位置 | API 端点 |
|------|------|---------|
| 启动项目 | Dashboard | POST `/api/projects/start-project` |
| 暂停项目 | Project Workspace 头部 | POST `/api/projects/{id}/pause` |
| 恢复项目 | Project Workspace 头部 | POST `/api/projects/{id}/resume` |
| 添加提示 | Project Workspace 头部 | POST `/api/projects/{id}/hint` |
| 批准 Review | Review Queue / Project Workspace | POST `/api/reviews/{id}/approve` |
| 拒绝 Review | Review Queue / Project Workspace | POST `/api/reviews/{id}/reject` |
| 修改 Review | Review Queue（未来） | POST `/api/reviews/{id}/modify` |

### 11.4 SSE 实时更新

Web UI 通过 `useSSE` hook 连接 `/api/events/stream`，侧边栏显示连接状态（Connected / Error / Connecting）。事件到达后视图自动更新，无需手动刷新。

---

## 12. REST API 参考

29 个端点，数据源为 Blackboard，不直接访问内部服务。

### 12.1 项目端点

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/projects` | 列出所有项目及状态 |
| GET | `/api/projects/{id}` | 单项目状态报告 |
| POST | `/api/projects/start-project` | 启动新项目（challenge_id 参数） |
| POST | `/api/projects/{id}/pause` | 暂停运行项目 |
| POST | `/api/projects/{id}/resume` | 恢复暂停项目 |
| POST | `/api/projects/{id}/hint` | 注入提示 |
| GET | `/api/projects/{id}/ideas` | 想法条目列表 |
| GET | `/api/projects/{id}/memory` | 去重事实记忆条目（limit=50） |
| GET | `/api/projects/{id}/solvers` | Solver 会话列表 |
| GET | `/api/projects/{id}/reviews` | 待处理 Review 请求 |
| GET | `/api/projects/{id}/events` | 完整事件回放日志 |
| GET | `/api/projects/{id}/observe` | 当前观察报告 |
| GET | `/api/projects/{id}/graph` | 物化状态（事实、想法、Solver、Packet） |
| GET | `/api/projects/{id}/observer-reports` | 观察报告事件 |
| GET | `/api/projects/{id}/candidate-flags` | 候选 flag 事件 |
| GET | `/api/projects/{id}/artifacts` | Artifact 事件 |
| GET | `/api/projects/{id}/replay-timeline` | 回放 + 人可读解释 |
| GET | `/api/projects/{id}/replay-steps` | 回放步骤 + 状态快照 |
| GET | `/api/projects/{id}/metrics` | 运行指标 |
| GET | `/api/projects/{id}/verify-consistency` | 验证 API 数据与 Blackboard 回放一致 |

### 12.2 Review 端点

| Method | Path | 说明 |
|--------|------|------|
| POST | `/api/reviews/{id}/approve` | 批准 Review 请求 |
| POST | `/api/reviews/{id}/reject` | 拒绝 Review 请求 |
| POST | `/api/reviews/{id}/modify` | 修改 Review 请求 |
| GET | `/api/reviews` | 全局 Review 队列（可选 status 过滤） |

### 12.3 Tool & 评估端点

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/tools` | 列出可用原语 |
| GET | `/api/tools/{name}` | 单个原语规格 |
| POST | `/api/projects/{id}/request-tool` | 为 Solver 请求工具 |
| POST | `/api/regression` | 运行回归对比 |

### 12.4 SSE 事件流

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/events/stream` | SSE 实时事件流 |

查询参数：`project_id`（可选过滤）、`last_event_id`（恢复断点）。

SSE 事件类型映射：

| EventType | SSE channel |
|-----------|------------|
| project_upserted | `project_updated` |
| worker_assigned / worker_heartbeat / worker_timeout | `solver_updated` |
| idea_proposed / idea_claimed / idea_verified / idea_failed | `idea_updated` |
| observation / memory_stored | `memory_added` |
| observer_report | `observer_reported` |
| security_validation (pending) | `review_created` |
| security_validation (decided) | `review_decided` |
| candidate_flag | `candidate_flag_found` |
| action_outcome / tool_request | `tool_event` |
| hint | `hint_added` |
| knowledge_packet_published | `knowledge_published` |
| knowledge_packet_merged | `knowledge_merged` |
