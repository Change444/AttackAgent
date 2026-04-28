# Change Log

本文件记录 AttackAgent 的版本演进、已完成里程碑和已解决限制。
写入后不再修改——新变更追加到末尾。

---

## Version History

| 版本 | 日期 | 变更说明 |
|------|------|----------|
| 3.5 | 2026-04-28 | P2 启发式自由探索 + 模式回注 + Embedding 接入：HeuristicFreeExplorationPlanner, FreeExplorationPlanner Protocol, PatternInjector + PatternLibrary 动态族, EmbeddingModel Protocol + adapters, InMemoryVectorStore cosine similarity, TF-IDF 修正, CJK tokenize, SemanticRetrievalConfig wiring |
| 3.4 | 2026-04-27 | P3 LLM 反馈闭环 + 原语参数化：ObservationSummarizer, step.parameters 参数化, ConstraintAwareReasoner enrichment, ReasoningContext.observation_summaries, 安全壳参数 scope 验证, FAMILY_PROGRAMS 保守参数化 |
| 3.3 | 2026-04-27 | 规划 P3 实施方案：记录 LLM 反馈闭环缺失 + 原语未参数化问题 |
| 3.2 | 2026-04-27 | CLI 入口 (`python -m attack_agent`)，AttackAgentConfig.from_defaults()，真实靶场 HTTP 集成测试 |
| 3.1 | 2026-04-27 | SecurityConstraints 与 SecurityConfig 对齐：默认值同步、from_config() 工厂方法、Dispatcher/Platform 接受外部约束 |
| 3.0 | 2026-04-26 | 真实 PrimitiveAdapter 实现，HttpSessionManager，completed_observations，CodeSandbox 增强 |
| 2.0 | 2026-04-25 | 添加双路径架构，完整重写 |
| 1.0 | — | 初始版本 |

---

## Completed Milestones

| 里程碑 | 目标 | 完成日期 |
|--------|------|----------|
| M1 | 自由探索路径可用 | 2026-04-25 |
| M2 | 双路径切换正常 | 2026-04-26 |
| M3 | 模式发现功能 | 2026-04-26 |
| M4 | 语义检索集成 | 2026-04-27 |
| M5 | 真实 PrimitiveAdapter | 2026-04-27 |
| M6 | LLM 反馈闭环 + 原语参数化 | 2026-04-27 |
| M7 | P2 启发式自由探索 + 模式回注 + Embedding | 2026-04-28 |

---

## Completed Priority Items

| 优先级 | 模块 | 工作量 | 完成日期 |
|--------|------|--------|----------|
| P0 | SecurityConstraints 与 SecurityConfig 对齐 | 1 天 | 2026-04-27 |
| P0 | ConstraintAwareReasoner | 3 天 | 2026-04-25 |
| P0 | EnhancedAPGPlanner | 2 天 | 2026-04-26 |
| P0 | 路径选择逻辑 | 2 天 | 2026-04-26 |
| P0 | 真实 PrimitiveAdapter | 4 天 | 2026-04-27 |
| P1 | DynamicPatternComposer | 4 天 | 2026-04-27 |
| P1 | SemanticRetrievalEngine | 5 天 | 2026-04-27 |
| P1 | CLI 入口 + 集成测试 | 2 天 | 2026-04-27 |
| P2 | 启发式自由探索 + 模式回注 + Embedding 接入 | 5 天 | 2026-04-28 |
| P3 | LLM 反馈闭环 + 原语参数化 | 4 天 | 2026-04-27 |

---

## Resolved Limitations

| 原限制 | 解决版本 | 解决方式 |
|--------|----------|----------|
| PrimitiveAdapter 模拟执行 | v3.0 | 9 个原语全部实现真实执行路径 |
| 语义检索仅 TF-IDF | v3.5 | InMemoryVectorStore cosine similarity + embedding, TF-IDF 实现修正, CJK tokenize |
| 模式图硬编码 | v3.5 | PatternInjector 回注动态模式到 PatternLibrary, APGPlanner._plan_candidates 使用动态族 |
| LLM 无执行反馈闭环 | v3.4 | ObservationSummarizer + `_extract_current_state()` 输出实际观测内容 |
| 原语未参数化 | v3.4 | `_resolve_*_specs()` 接受 `step.parameters` 覆盖, `_step_param_overrides()` helper |
| SecurityConstraints 硬编码 | v3.1 | `SecurityConstraints.from_config(SecurityConfig)` 单一源, 默认值对齐 |
| 无 CLI 入口 | v3.2 | `__main__.py` 提供 `python -m attack_agent` 入口 |
| 无启发式自由探索 | v3.5 | HeuristicFreeExplorationPlanner, model=None 时双路径自动切换 |

---

## Current Limitations & Roadmap

### 已识别问题清单

#### 执行层原语能力缺陷

| # | 问题 | 影响范围 | 严重度 |
|---|------|----------|--------|
| E1 | browser-inspect 不执行 JS 且丢弃 `<script>` 标签内容 | 所有 JS 渲染页面、XSS 发现、DOM 操纵类 web 题（约 40% CTF） | 致命 |
| E2 | http-request 无 multipart 文件上传、无 HTTP Basic Auth、无 SSL 自签名证书支持 | 文件上传题、Basic Auth 保护页面、HTTPS 自签名靶场 | 致命 |
| E3 | session-materialize 仅 form POST 登录，无 CSRF token 预取、无 JSON body 登录、无多步认证 | Django/Flask-WTF 等 CSRF 站点、API 登录、2FA | 致命 |
| E4 | code-sandbox 禁止 class/lambda/with/raise，无 crypto 库 | RSA/AES/ECC 类密码题、复杂算法 | 高 |
| E5 | artifact-scan 不提取 ZIP/tar 内容（仅列文件名），预览仅 64 字节，下载后立即清理临时文件 | Forensics 取证题、需要多步分析的文件题 | 高 |
| E6 | binary-inspect 无反汇编、无熵分析、strings 限制 20 条 | Reverse 逆向题 | 高 |
| E7 | extract-candidate 仅正则匹配，无启发式 flag 检测 | 非 `flag{}` 格式的 flag | 中 |
| E8 | 原语无 retry 逻辑，网络失败直接返回 failed | 瞬态故障场景 | 低 |

#### 接入层 Provider 缺陷

| # | 问题 | 影响范围 | 严重度 |
|---|------|----------|--------|
| P1 | LocalHTTPCompetitionProvider 使用私有 6 端点 API，无真实 CTF 平台（CTFd/HackTheBox/PicoCTF）适配器 | 无法对接任何真实靶场 | 致命 |
| P2 | HTTP transport 无认证机制（无 API key / session token / JWT） | 需要认证的靶场全部无法接入 | 致命 |
| P3 | 实例生命周期模型与真实 CTF 不匹配 | 静态挑战、动态容器等场景 | 高 |

#### 规划层策略缺陷

| # | 问题 | 影响范围 | 严重度 |
|---|------|----------|--------|
| S1 | 6 个族关键词过浅，缺少 SSRF/SSTI/CSRF/IDOR/RSA/pwn/协议分析等族 | 多数 CTF 类别无匹配，无匹配时返回 None | 致命 |
| S2 | FAMILY_PROGRAMS 步骤不含挑战特定参数（URL/路径/payload） | 步骤是空模板，无法执行具体操作 | 高 |
| S3 | 停滞阈值 3 次连续失败就放弃 | 真实解题通常需 10+ 次迭代 | 高 |
| S4 | max_cycles 默认 12 次 | 远不够真实解题所需 | 高 |
| S5 | switch_path() 是空 stub | 文档声称有路径切换功能，实际不存在 | 高 |
| S6 | flag 提交置信度阈值 0.85 过高 | 可能拒绝正确 flag | 中 |
| S7 | 无多族组合攻击链 | 只选最高得分族，无法组合跨族策略 | 中 |
| S8 | catch-22：DynamicPatternComposer 需要 3+ 成功案例，但 3 水失败就放弃 | 模式发现闭环无法闭合 | 中 |

#### 架构结构性问题

| # | 问题 | 说明 | 严重度 |
|---|------|------|--------|
| A1 | 原语双路径膨胀 | 每个原语有真实+回退两条路径，runtime.py 1629 行，假数据掩盖能力不足 | 高 |
| A2 | 模式图过于静态 | PatternLibrary.build() 一次性构建，运行中只标记节点状态不重组 | 中 |
| A3 | Dispatcher/Strategy 6 层间接调用 | 最终效果只是"选一个族模板执行它" | 低 |

#### 当前能解 vs 不能解

**勉强能解（约 10-15% CTF 题）**：
- 简单 HTTP GET 页面 + HTML 注释隐藏 flag
- 简单 base64/xor/hex 编码题（code-sandbox 可解）
- 简单 form POST 登录后获取 flag
- JSON API 响应中直接包含 flag

**完全不能解（约 85% CTF 题）**：
- JS 渲染/JS 操纵类 web 题
- 文件上传、SSRF、CSRF、SSTI、IDOR、race condition
- 现代密码题（RSA、AES、padding oracle）
- Reverse/pwn 题
- Forensics 取证题（ZIP 内容不提取、无 pcap/EXIF）
- 多步认证、OAuth、JWT 操纵类

---

### 四阶段解决计划

#### Phase 1：让系统能跑起来（P0，约 5 天）

| # | 任务 | 工作量 | 交付物 |
|---|------|--------|--------|
| R1 | 参数调优：max_cycles→50, 停滞阈值→8, 提交置信度→0.6 | 0.5 天 | 配置变更 + 测试 |
| R2 | CTFd Provider 适配器（含 session auth） | 3 天 | `ctfd_provider.py` + 测试 |
| R3 | 删除 `_consume_metadata` 假数据路径 | 1.5 天 | runtime.py 精简 + 测试更新 |

**Phase 1 目标**：系统连接真实 CTFd 靶场，原语真执行或干净失败，不再假装工作。

#### Phase 2：补齐原语能力（P1，约 5 天）

| # | 任务 | 工作量 | 交付物 |
|---|------|--------|--------|
| R4 | browser-inspect 接 Playwright | 2 天 | JS 渲染 + script 读取 + 测试 |
| R5 | http-request 接 requests + multipart + Basic Auth + SSL | 1 天 | 文件上传 + 认证 + 测试 |
| R6 | session-materialize CSRF 预取 + JSON body | 1 天 | CSRF token + JSON 登录 + 测试 |
| R7 | artifact-scan 提取 ZIP/tar 内容 + 保留临时文件 + 增大预览 | 0.5 天 | 完整文件分析 + 测试 |
| R8 | code-sandbox 放宽：class/with/raise + 加 zlib/csv | 0.5 天 | 更强解码能力 + 测试 |

**Phase 2 目标**：原语覆盖 70%+ 常见 web/encoding/forensics 类 CTF 题。

#### Phase 3：规划策略增强（P2，约 3 天）

| # | 任务 | 工作量 | 交付物 |
|---|------|--------|--------|
| R9 | 扩展 FAMILY_KEYWORDS：+SSRF/SSTI/CSRF/IDOR/RSA/pwn/协议等 8 族 | 1 天 | 14 族关键词 + FAMILY_PROGRAMS + 测试 |
| R10 | 步骤参数注入：挑战 target/endpoint/credential 注入步骤模板 | 1 天 | 动态参数填充 + 测试 |
| R11 | 实现 switch_path() 真实逻辑 | 0.5 天 | 路径切换 + 测试 |
| R12 | 多族组合：允许 plan 融合 2 个族的步骤 | 0.5 天 | 组合策略 + 测试 |

**Phase 3 目标**：规划覆盖主流 CTF 类别，步骤不再只是空模板。

#### Phase 4：架构清理（P3，约 2 天）

| # | 任务 | 工作量 | 交付物 |
|---|------|--------|--------|
| R13 | 合并 SecurityConstraints → SecurityConfig（消除重复） | 0.5 天 | 单一约束源 |
| R14 | 更新 ARCHITECTURE.md 与代码对齐 | 0.5 天 | 文档-代码一致 |
| R15 | 简化 Dispatcher/StrategyLayer 间接层 | 1 天 | 合并冗余层 |

**Phase 4 目标**：代码架构清晰，文档准确，无冗余间接层。

---

### Phase 6 遗留项（原计划）

| 项目 | 状态 |
|------|------|
| 实现路径选择自适应 | → 合入 Phase 3 R11 |
| 添加性能监控 | 未开始 |
| 优化检索质量 | 未开始 |
| 优化规划延迟 | 未开始 |