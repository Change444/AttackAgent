# Change Log

本文件记录 AttackAgent 的版本演进、已完成里程碑和已解决限制。
写入后不再修改——新变更追加到末尾。

---

## Version History

| 版本 | 日期 | 变更说明 |
|------|------|----------|
| 4.1 | 2026-04-30 | Phase 4 架构清理：SecurityConstraints 删除→SecurityConfig 直接作为约束源（消除重复类+from_config桥接），SecurityConfig 新增 forbidden_primitive_combinations 字段；StrategyLayer 删除→Dispatcher 内联策略逻辑（stagnation/submit/stage），strategy.py 仅保留 SubmitClassifier+TaskPromptCompiler；ARCHITECTURE.md v4.1 对齐更新 |
| 3.16 | 2026-04-29 | Phase 3 R11+R12 switch_path 真实逻辑 + 多族组合：EnhancedAPGPlanner.switch_path() 实现 STRUCTURED→FREE_EXPLORATION(停滞≥3时自动切换) + FREE_EXPLORATION→STRUCTURED(预算耗尽或置信度≥0.7时回切) + 停滞计数器(_stagnation_counters) + record_outcome() + PATH_SELECTION 事件记录 + stagnation reset，_compose_multi_family_candidates() 融合 2 族步骤(观察阶段用主族 + 操作阶段用副族 + 验证阶段用主族，副族得分≥0.7×主族得分时组合) + PlanCandidate.secondary_families + ProgramDecision.secondary_families + ActionProgram 融合描述/rationale + HeuristicFreeExplorationPlanner 多族融合 + DualPathConfig.path_switch_stagnation_threshold + DualPathConfig.multi_family_score_ratio + StrategyLayer.update_after_outcome 调用 record_outcome，12 项新测试(6 项 R11 + 6 项 R12)，330 测试通过 |
| 3.15 | 2026-04-29 | Phase 3 R10 步骤参数注入：_inject_challenge_params() 在规划阶段注入 target URL 到 http-request(url)/browser-inspect(url)/session-materialize(login_url)/artifact-scan(url)/binary-inspect(url) 步骤模板(setdefault 不覆盖已有参数)，runtime _resolve_http_request_specs/_resolve_browser_inspect_specs/_resolve_session_materialize_specs 增加 bundle.target 回退(metadata+param_overrides 均空时)，APGPlanner._plan_candidates() + HeuristicFreeExplorationPlanner 调用注入，8 项注入单元测试 + 1 项 APG 集成测试 + 1 项启发式集成测试 + 3 项 runtime 回退测试，318 测试通过 |
| 3.14 | 2026-04-29 | Phase 3 R9 扩展族关键词 6→14：新增 ssrf-server-boundary(ssrf/internal/proxy/metadata/9关键词) + ssti-template-boundary(ssti/jinja/mako/twig/10关键词) + csrf-state-boundary(csrf/cross-site/forgery/referer/8关键词) + idor-access-boundary(idor/insecure/privilege/uuid/10关键词) + crypto-math-boundary(rsa/aes/ecb/cbc/padding/oracle/16关键词) + pwn-memory-boundary(pwn/overflow/rop/gadget/13关键词) + protocol-logic-boundary(protocol/tcp/dns/mqtt/serialization/14关键词) + race-condition-boundary(race/concurrent/toctou/11关键词)，FAMILY_PROFILES + FAMILY_PROGRAMS 各 8 族 4 节点完整步骤，8 项族匹配测试 + 2 项启发式测试 + 14 族完整性 + 关键词重叠检查，305 测试通过 |
| 3.13 | 2026-04-29 | Phase 2 R8 code-sandbox 放宽：_SafeAstValidator 移除 ClassDef/With/Raise 禁止(添加 visit_ClassDef 跟踪类名), SAFE_IMPORTS 加入 zlib/csv(9→11), SAFE_BUILTINS 加入 __build_class__, globals_scope 加入 __name__, ConstraintAwareReasoner 更新 code-sandbox 描述, 测试新增 class/with/raise/zlib/csv 5 项, 297 测试通过 |
| 3.12 | 2026-04-29 | Phase 2 R7 artifact-scan 提取 ZIP/tar 内容 + 增大预览：_extract_archive_members 添加 content_preview(ZIP/tar 成员文本内容) + content_type(_guess_content_type 扩展名映射), _extract_text_preview 上限 128→4096 默认 64→512, _perform_artifact_scan 返回 (payload, temp_dir) 元组延迟清理, _execute_artifact_scan 批量清理 temp_dirs, Observation payload 新增 content_type 字段, PrimitiveRegistry + ConstraintAwareReasoner 新增 max_depth/max_members 参数, 292 测试全通过 |
| 3.11 | 2026-04-29 | Phase 2 R6 session-materialize CSRF 预取 + JSON body：_CSRFTokenParser(HTML hidden input + meta tag 解析), _extract_csrf_token(csrf_field/csrf_source 自动检测), _execute_session_materialize CSRF GET 预取(form/meta/header 3 来源) + JSON body 登录(json/content_type spec 字段) + auth token 持久化回写 session_manager.add_auth_header(), Observation payload 新增 csrf_prefetched/csrf_token_value/body_type 字段, PrimitiveRegistry + ConstraintAwareReasoner 新字段, 284 测试全通过 |
| 3.10 | 2026-04-29 | Phase 2 R5 http-request 接 requests：HttpConfig(engine/verify_ssl/max_redirects/timeout_seconds), RequestsHttpClient(multipart + Basic Auth + Bearer Auth + SSL bypass), StdlibHttpClient(graceful fallback), HttpSessionManager.auth_headers 持久化, _resolve_http_request_specs 新增 auth/auth_type/auth_token/files/verify_ssl 字段, Observation payload 新增 auth_used/ssl_verified/uploaded_files 字段, WorkerRuntime 接 http_config, 276 测试全通过 |
| 3.9 | 2026-04-28 | Phase 2 R4 browser-inspect 接 Playwright：BrowserConfig(engine/headless/browser_type/timeout/wait_for_selector/extract_scripts), PlaywrightBrowserInspector(JS 渲染 + script 读取 + console + cookies), StdlibBrowserInspector(graceful fallback), _HTMLPageParser extract_scripts 模式, Observation payload 新增 scripts/js_rendered_text/console_messages/cookies 字段, WorkerRuntime 接 browser_config, 252 测试全通过 |
| 3.5 | 2026-04-28 | P2 启发式自由探索 + 模式回注 + Embedding 接入：HeuristicFreeExplorationPlanner, FreeExplorationPlanner Protocol, PatternInjector + PatternLibrary 动态族, EmbeddingModel Protocol + adapters, InMemoryVectorStore cosine similarity, TF-IDF 修正, CJK tokenize, SemanticRetrievalConfig wiring |
| 3.6 | 2026-04-28 | Phase 1 R1 参数调优：stagnation_threshold 3→8 可配置, flag_confidence_threshold 0.85→0.6 可配置, StrategyLayer/SubmitClassifier 构造参数化, CLI override 支持 |
| 3.7 | 2026-04-28 | Phase 1 R2 CTFd 适配器：CTFdCompetitionProvider (session auth + API token), 6 方法 Protocol 实现, CLI --ctfd-url/--ctfd-username/--ctfd-password/--ctfd-token |
| 3.8 | 2026-04-28 | Phase 1 R3 删除假数据路径：_consume_metadata/_hash_payload 删除, _clean_fail 替换 10 个调用点, _extract_candidates/structured-parse/diff-compare 元数据回退删除, runtime.py 1629→1502 行, 测试改写验证干净失败 |
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
| M8 | Phase 1 R1 参数调优 | 2026-04-28 |
| M9 | Phase 1 R2 CTFd 适配器 | 2026-04-28 |
| M10 | Phase 1 R3 删除假数据路径 | 2026-04-28 |
| M11 | Phase 2 R4 browser-inspect 接 Playwright | 2026-04-28 |
| M12 | Phase 2 R5 http-request 接 requests | 2026-04-29 |
| M13 | Phase 2 R6 session-materialize CSRF + JSON body | 2026-04-29 |
| M14 | Phase 2 R7 artifact-scan ZIP/tar 内容提取 + 增大预览 | 2026-04-29 |
| M15 | Phase 2 R8 code-sandbox 放宽 class/with/raise + zlib/csv | 2026-04-29 |
| M16 | Phase 3 R9 扩展族关键词 6→14 | 2026-04-29 |
| M17 | Phase 3 R10 步骤参数注入 | 2026-04-29 |
| M18 | Phase 3 R11 switch_path 真实逻辑 | 2026-04-29 |
| M19 | Phase 3 R12 多族组合 | 2026-04-29 |
| M20 | Phase 4 R13 合并 SecurityConstraints → SecurityConfig | 2026-04-30 |
| M21 | Phase 4 R14 更新 ARCHITECTURE.md 与代码对齐 | 2026-04-30 |
| M22 | Phase 4 R15 简化 Dispatcher/StrategyLayer 间接层 | 2026-04-30 |

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
| P0 | 参数调优（stagnation/confidence 可配置） | 0.5 天 | 2026-04-28 |
| P0 | CTFd Provider 适配器（session auth + API token） | 3 天 | 2026-04-28 |
| P0 | 删除 _consume_metadata 假数据路径（原语真执行或干净失败） | 1.5 天 | 2026-04-28 |
| P1 | browser-inspect 接 Playwright（JS 渲染 + script 读取） | 2 天 | 2026-04-28 |
| P1 | http-request 接 requests（multipart + Basic Auth + SSL bypass） | 1 天 | 2026-04-29 |
| P1 | session-materialize CSRF 预取 + JSON body（CSRF 3 来源 + JSON 登录 + auth 持久化） | 1 天 | 2026-04-29 |
| P1 | artifact-scan 提取 ZIP/tar 内容 + 保留临时文件 + 增大预览（content_preview + content_type + 预览 512→4096） | 0.5 天 | 2026-04-29 |
| P1 | code-sandbox 放宽（class/with/raise 允许 + zlib/csv 导入） | 0.5 天 | 2026-04-29 |
| P2 | 扩展族关键词 6→14（+SSRF/SSTI/CSRF/IDOR/RSA/pwn/协议/竞态） | 1 天 | 2026-04-29 |
| P2 | 步骤参数注入（_inject_challenge_params + bundle.target 回退） | 1 天 | 2026-04-29 |
| P2 | switch_path 真实逻辑（STRUCTURED→FREE_EXPLORATION 停滞切换 + FREE_EXPLORATION→STRUCTURED 回切 + stagnation counter + PATH_SELECTION 事件） | 0.5 天 | 2026-04-29 |
| P2 | 多族组合（_compose_multi_family_candidates 融合 2 族步骤 + PlanCandidate.secondary_families + HeuristicFree 多族融合） | 0.5 天 | 2026-04-29 |

---

## Resolved Limitations

| 原限制 | 解决版本 | 解决方式 |
|--------|----------|----------|
| PrimitiveAdapter 模拟执行 | v3.0 | 9 个原语全部实现真实执行路径 |
| 语义检索仅 TF-IDF | v3.5 | InMemoryVectorStore cosine similarity + embedding, TF-IDF 实现修正, CJK tokenize |
| 模式图硬编码 | v3.5 | PatternInjector 回注动态模式到 PatternLibrary, APGPlanner._plan_candidates 使用动态族 |
| LLM 无执行反馈闭环 | v3.4 | ObservationSummarizer + `_extract_current_state()` 输出实际观测内容 |
| 原语未参数化 | v3.4 | `_resolve_*_specs()` 接受 `step.parameters` 覆盖, `_step_param_overrides()` helper |
| SecurityConstraints 硬编码 | v3.1→v4.1 | v3.1 `SecurityConstraints.from_config(SecurityConfig)` 单一源 → v4.1 SecurityConstraints 删除，SecurityConfig 直接作为 LightweightSecurityShell 约束源 |
| 无 CLI 入口 | v3.2 | `__main__.py` 提供 `python -m attack_agent` 入口 |
| 无启发式自由探索 | v3.5 | HeuristicFreeExplorationPlanner, model=None 时双路径自动切换 |
| 停滞阈值/提交置信度硬编码 | v3.6 | StrategyLayer 构造参数化, stagnation_threshold→8, confidence_threshold→0.6, PlatformConfig 可配置 |
| 无 CTFd 靶场适配器 | v3.7 | CTFdCompetitionProvider 实现 6 方法 Protocol, session auth + API token, CLI --ctfd-* 参数 |
| 原语假数据回退掩盖能力不足 | v3.8 | _consume_metadata 删除, 10 个调用点改为 _clean_fail 干净失败, _extract_candidates 不再读取 primitive_payloads, runtime.py 精简 127 行 |
| browser-inspect 不执行 JS 且丢弃 `<script>` 标签内容 | v3.9 | PlaywrightBrowserInspector(JS 渲染 + script 读取 + console + cookies), StdlibBrowserInspector(graceful fallback), _HTMLPageParser extract_scripts 模式, BrowserConfig(engine/headless/browser_type/timeout/wait_for_selector/extract_scripts) |
| http-request 无 multipart 文件上传、无 HTTP Basic Auth、无 SSL 自签名证书支持 | v3.10 | RequestsHttpClient(multipart + Basic Auth + Bearer Auth + SSL bypass), StdlibHttpClient(graceful fallback), HttpSessionManager.auth_headers 持久化, HttpConfig(engine/verify_ssl/max_redirects/timeout_seconds) |
| session-materialize 仅 form POST 登录（CSRF/JSON body 部分） | v3.11 | _CSRFTokenParser + _extract_csrf_token(CSRF 3 来源), JSON body 登录(json/content_type), auth token 持久化回写 session_manager.add_auth_header(), Observation payload csrf_prefetched/csrf_token_value/body_type |
| artifact-scan 不提取 ZIP/tar 内容（仅列文件名），预览仅 64 字节，下载后立即清理临时文件 | v3.12 | _extract_archive_members 添加 content_preview(ZIP/tar 成员文本预览) + content_type(_guess_content_type 扩展名→MIME 映射), _extract_text_preview 上限 128→4096 默认 64→512, _perform_artifact_scan 返回 (payload, temp_dir) 元组延迟清理, Observation payload 新增 content_type 字段 |
| code-sandbox 禁止 class/with/raise，缺少 zlib/csv 解码库 | v3.13 | _SafeAstValidator 移除 ClassDef/With/Raise 禁止 + visit_ClassDef 跟踪类名, SAFE_IMPORTS 加入 zlib/csv, SAFE_BUILTINS 加入 __build_class__, globals_scope 加入 __name__, class/with/raise 可用 |
| 6 个族关键词过浅，缺少 SSRF/SSTI/CSRF/IDOR/RSA/pwn/协议分析等族 | v3.14 | FAMILY_KEYWORDS 6→14，新增 ssrf-server/ssti-template/csrf-state/idor-access/crypto-math/pwn-memory/protocol-logic/race-condition 8 族，FAMILY_PROFILES + FAMILY_PROGRAMS 4 节点完整步骤，族关键词覆盖常见 CTF 类别(web/crypto/pwn/forensics/protocol) |
| FAMILY_PROGRAMS 步骤不含挑战特定 URL/路径参数 | v3.15 | _inject_challenge_params() 在规划阶段注入 challenge.target→url/login_url 到模板步骤(setdefault 不覆盖)，runtime _resolve_*_specs() 增加 bundle.target 回退(metadata+param_overrides 均空时) |
| switch_path() 是空 stub | v3.16 | EnhancedAPGPlanner.switch_path() 实现 STRUCTURED→FREE_EXPLORATION(停滞≥3自动切换) + FREE_EXPLORATION→STRUCTURED(预算耗尽或置信度≥0.7回切) + _stagnation_counters + record_outcome() + PATH_SELECTION 事件 + stagnation reset |
| 无多族组合攻击链 | v3.16 | _compose_multi_family_candidates() 融合 2 族步骤(观察→主族 + 操作→副族 + 验证→主族，副族得分≥0.7×主族)，PlanCandidate.secondary_families + ProgramDecision.secondary_families + HeuristicFree 多族融合 + DualPathConfig.multi_family_score_ratio |

---

## Current Limitations & Roadmap

### 已识别问题清单

#### 执行层原语能力缺陷

| # | 问题 | 影响范围 | 严重度 |
|---|------|----------|--------|
| E1 | browser-inspect 不执行 JS 且丢弃 `<script>` 标签内容 | 所有 JS 渲染页面、XSS 发现、DOM 操纵类 web 题（约 40% CTF） | 致命 |
| E2 | ~~http-request 无 multipart 文件上传、无 HTTP Basic Auth、无 SSL 自签名证书支持~~ → 已解决 | ~~文件上传题、Basic Auth 保护页面、HTTPS 自签名靶场~~ → v3.10 RequestsHttpClient(multipart + Basic Auth + Bearer Auth + SSL bypass), StdlibHttpClient(graceful fallback), HttpSessionManager.auth_headers |
| E3 | ~~session-materialize 仅 form POST 登录~~ → 部分解决 | ~~Django/Flask-WTF 等 CSRF 站点、API 登录~~ → v3.11 CSRF 预取(form/meta/header) + JSON body + auth 持久化已实现；多步认证(2FA/OAuth)仍 TODO | ~~致命~~ → 降为高 |
| E4 | ~~code-sandbox 禁止 class/lambda/with/raise，无 crypto 库~~ → 部分解决 | ~~RSA/AES/ECC 类密码题、复杂算法~~ → v3.13 class/with/raise 允许 + zlib/csv 导入；lambda 仍禁止 + crypto 库(cryptography/pycryptodome)仍不可用 | ~~高~~ → 降为中 |
| E5 | ~~artifact-scan 不提取 ZIP/tar 内容（仅列文件名），预览仅 64 字节，下载后立即清理临时文件~~ → 已解决 | ~~Forensics 取证题、需要多步分析的文件题~~ → v3.12 content_preview(ZIP/tar 成员文本) + content_type(MIME 映射) + 预览 512→4096 + temp_dir 延迟清理 | ~~高~~ → 已解决 |
| E6 | binary-inspect 无反汇编、无熵分析、strings 限制 20 条 | Reverse 逆向题 | 高 |
| E7 | extract-candidate 仅正则匹配，无启发式 flag 检测 | 非 `flag{}` 格式的 flag | 中 |
| E8 | 原语无 retry 逻辑，网络失败直接返回 failed | 瞬态故障场景 | 低 |

#### 接入层 Provider 缺陷

| # | 问题 | 影响范围 | 严重度 |
|---|------|----------|--------|
| P1 | ~~无真实 CTF 平台适配器~~ → 已解决 | 无法对接任何真实靶场 → v3.7 CTFdCompetitionProvider 实现 6 方法 Protocol | ~~致命~~ → 已解决 |
| P2 | ~~HTTP transport 无认证机制~~ → 已解决 | 需要认证的靶场全部无法接入 → v3.7 CTFd session auth + API token | ~~致命~~ → 已解决 |
| P3 | 实例生命周期模型与真实 CTF 不匹配 | 静态挑战、动态容器等场景 | 高 |

#### 规划层策略缺陷

| # | 问题 | 影响范围 | 严重度 |
|---|------|----------|--------|
| S1 | ~~6 个族关键词过浅，缺少 SSRF/SSTI/CSRF/IDOR/RSA/pwn/协议分析等族~~ → 已解决 | ~~多数 CTF 类别无匹配，无匹配时返回 None~~ → v3.14 族关键词 6→14，覆盖 SSRF/SSTI/CSRF/IDOR/crypto/pwn/协议/竞态 8 族，FAMILY_PROGRAMS 4 节点完整步骤 | ~~致命~~ → 已解决 |
| S2 | ~~FAMILY_PROGRAMS 步骤不含挑战特定参数（URL/路径/payload）~~ → 部分解决 | ~~步骤是空模板，无法执行具体操作~~ → v3.15 _inject_challenge_params() 填充 url/login_url，runtime 回退 bundle.target；parse_source/program_fragment/diff-compare 仍需 metadata 或 LLM 提供 | ~~高~~ → 降为中 |
| S3 | ~~停滞阈值 3 次连续失败就放弃~~ → 已解决 | 真实解题通常需 10+ 次迭代 → v3.6 stagnation_threshold→8 可配置 | ~~高~~ → 已解决 |
| S4 | max_cycles 默认 12 次 | 远不够真实解题所需 | 高 |
| S5 | ~~switch_path() 是空 stub~~ → 已解决 | ~~文档声称有路径切换功能，实际不存在~~ → v3.16 switch_path() 实现 STRUCTURED→FREE_EXPLORATION(停滞≥3自动切换) + FREE_EXPLORATION→STRUCTURED(预算耗尽或置信度≥0.7回切) + stagnation counter + PATH_SELECTION 事件 | ~~高~~ → 已解决 |
| S6 | ~~flag 提交置信度阈值 0.85 过高~~ → 已解决 | 可能拒绝正确 flag → v3.6 flag_confidence_threshold→0.6 可配置 | ~~中~~ → 已解决 |
| S7 | ~~无多族组合攻击链~~ → 已解决 | ~~只选最高得分族，无法组合跨族策略~~ → v3.16 _compose_multi_family_candidates() 融合 2 族步骤(观察→主族 + 操作→副族 + 验证→主族，副族得分≥0.7×主族得分) + PlanCandidate.secondary_families | ~~中~~ → 已解决 |
| S8 | catch-22：DynamicPatternComposer 需要 3+ 成功案例，但 3 水失败就放弃 | 模式发现闭环无法闭合 | 中 |

#### 架构结构性问题

| # | 问题 | 说明 | 严重度 |
|---|------|------|--------|
| A1 | ~~原语双路径膨胀~~ → 已解决 | 每个原语有真实+回退两条路径，假数据掩盖能力不足 → v3.8 删除假数据路径，原语真执行或干净失败，runtime.py 1629→1502 行 | ~~高~~ → 已解决 |
| A2 | 模式图过于静态 | PatternLibrary.build() 一次性构建，运行中只标记节点状态不重组 | 中 |
| A3 | ~~Dispatcher/Strategy 6 层间接调用~~ → 已解决 | StrategyLayer 是极薄 wrapper → v4.1 StrategyLayer 删除，Dispatcher 内联策略逻辑(stagnation/submit/stage)，strategy.py 仅保留 SubmitClassifier+TaskPromptCompiler | ~~低~~ → 已解决 |

#### 当前能解 vs 不能解

**勉强能解（约 25-30% CTF 题）**：
- 简单 HTTP GET 页面 + HTML 注释隐藏 flag
- 简单 base64/xor/hex/zlib 压缩/CSV 解析编码题（code-sandbox class/with/raise 可解）
- 简单 class 结构化解码（RSA/AES 参数组装、自定义解码器）
- with 上下文管理器模式（资源清理、文件操作模拟）
- 简单 form POST 登录后获取 flag
- JSON API 响应中直接包含 flag
- Basic Auth 保护页面
- Bearer token 保护 API
- 文件上传 web 题
- HTTPS 自签名靶场
- CSRF token 保护登录页面（Django/Flask-WTF 等）
- JSON body API 登录
- ZIP/tar 内嵌 flag（内容提取 + 文本预览）
- SSRF 类题（族关键词匹配 + HTTP 探测，但复杂 SSRF 仍受限）
- SSTI 类题（族关键词匹配 + 模板注入探测，但高级 SSTI 需 JS 渲染）
- IDOR 类题（族关键词匹配 + 身份切换探测）
- 简单密码题（族关键词匹配 + code-sandbox 数学运算）
- pwn 类题（族关键词匹配 + binary-inspect 基础分析）
- 协议分析类题（族关键词匹配 + artifact-scan pcap 扫描）

**完全不能解（约 60-65% CTF 题）**：
- JS 渲染/JS 操纵类 web 题（Playwright 可渲染，但复杂 DOM 操纵仍受限）
- 现代密码题（RSA/AES/padding oracle，crypto 库不可用）
- Reverse/pwn 题（无反汇编、无调试器）
- Forensics 取证题（无 pcap 深度分析、无 EXIF/磁盘映像）
- 多步认证（2FA、OAuth、JWT 操纵）
- 复杂竞态条件（无并发请求基础设施）

---

### 四阶段解决计划

#### Phase 1：让系统能跑起来（P0，已完成 ✅）

| # | 任务 | 工作量 | 交付物 | 完成日期 |
|---|------|--------|--------|----------|
| R1 | 参数调优：max_cycles→50, 停滞阈值→8, 提交置信度→0.6 | 0.5 天 | 配置变更 + 测试 | 2026-04-28 |
| R2 | CTFd Provider 适配器（含 session auth） | 3 天 | `ctfd_provider.py` + 测试 | 2026-04-28 |
| R3 | 删除 `_consume_metadata` 假数据路径 | 1.5 天 | runtime.py 精简 + 测试更新 | 2026-04-28 |

**Phase 1 目标已达成**：系统连接真实 CTFd 靶场，原语真执行或干净失败，不再假装工作。

#### Phase 2：补齐原语能力（P1，约 5 天）

| # | 任务 | 工作量 | 交付物 | 完成日期 |
|---|------|--------|--------|----------|
| R4 | browser-inspect 接 Playwright | 2 天 | JS 渲染 + script 读取 + 测试 | 2026-04-28 |
| R5 | http-request 接 requests + multipart + Basic Auth + SSL | 1 天 | 文件上传 + 认证 + 测试 | 2026-04-29 |
| R6 | session-materialize CSRF 预取 + JSON body | 1 天 | CSRF token + JSON 登录 + 测试 | 2026-04-29 |
| R7 | artifact-scan 提取 ZIP/tar 内容 + 保留临时文件 + 增大预览 | 0.5 天 | 完整文件分析 + 测试 | 2026-04-29 |
| R8 | code-sandbox 放宽：class/with/raise + 加 zlib/csv | 0.5 天 | 更强解码能力 + 测试 | 2026-04-29 |

**Phase 2 目标**：原语覆盖 70%+ 常见 web/encoding/forensics 类 CTF 题。

#### Phase 3：规划策略增强（P2，已完成 ✅）

| # | 任务 | 工作量 | 交付物 | 完成日期 |
|---|------|--------|--------|----------|
| R9 | 扩展 FAMILY_KEYWORDS：+SSRF/SSTI/CSRF/IDOR/RSA/pwn/协议等 8 族 | 1 天 | 14 族关键词 + FAMILY_PROGRAMS + 测试 | 2026-04-29 |
| R10 | 步骤参数注入：挑战 target/endpoint/credential 注入步骤模板 | 1 天 | 动态参数填充 + 测试 | 2026-04-29 |
| R11 | 实现 switch_path() 真实逻辑 | 0.5 天 | 路径切换 + 测试 | 2026-04-29 |
| R12 | 多族组合：允许 plan 融合 2 个族的步骤 | 0.5 天 | 组合策略 + 测试 | 2026-04-29 |

**Phase 3 目标已达成**：规划覆盖主流 CTF 类别，步骤不再只是空模板，路径可自动切换，多族组合增强策略覆盖。

#### Phase 4：架构清理（P3，已完成 ✅）

| # | 任务 | 工作量 | 交付物 | 完成日期 |
|---|------|--------|--------|----------|
| R13 | 合并 SecurityConstraints → SecurityConfig（消除重复） | 0.5 天 | 单一约束源 | 2026-04-30 |
| R14 | 更新 ARCHITECTURE.md 与代码对齐 | 0.5 天 | 文档-代码一致 | 2026-04-30 |
| R15 | 简化 Dispatcher/StrategyLayer 间接层 | 1 天 | 合并冗余层 | 2026-04-30 |

**Phase 4 目标已达成**：代码架构清晰，文档准确，无冗余间接层。SecurityConstraints 删除，SecurityConfig 直接作为约束源；StrategyLayer 删除，Dispatcher 内联策略逻辑。

---

### Phase 6 遗留项（原计划）

| 项目 | 状态 |
|------|------|
| 实现路径选择自适应 | → 合入 Phase 3 R11 |
| 添加性能监控 | 未开始 |
| 优化检索质量 | 未开始 |
| 优化规划延迟 | 未开始 |

---

## 2026-04-30 运行验证记录：测试提速与真实模型联调

### 背景

本次验证目标是确认当前项目能否正常工作，并定位全量测试耗时过长的问题。验证范围包括：
- 本地单元/集成测试：`python -m unittest discover tests/ -v`
- CLI heuristic 冒烟：`python -m attack_agent --config config/settings.json --max-cycles 12 --verbose`
- OpenAI 兼容接口真实模型联调：通过 `config/local-openai-compatible.json` + `ATTACK_AGENT_API_KEY`/本地密钥配置

### 已解决问题

1. **全量测试耗时过长**
   - 根因：`tests/test_platform_flow.py` 中多个失败路径测试使用生产默认 HTTP/browser timeout，并重复执行 `solve_all(max_cycles=12)`；无真实 target 时会反复等待网络超时。
   - 修复：为 platform flow 测试增加测试专用 `fast_test_config()`，使用 stdlib HTTP/browser、短 timeout、短 stagnation/path-switch 阈值；将该模块中的 `solve_all(max_cycles=12)` 收敛为 `FAST_SOLVE_CYCLES = 3`。
   - 结果：全量测试从约 **292s** 降到约 **36s**；`test_platform_flow` 从约 **5min+** 降到约 **14s**。

2. **重复集成测试浪费时间**
   - 根因：console summary/pattern/journal 三个测试各自重新跑一次完整 platform flow；`http_request_without_real_target` 与 identity 无真实 target 测试覆盖同一失败语义。
   - 修复：合并 console 输出测试为一个用例；删除重复的 HTTP 无真实 target 测试，保留 identity/http 失败语义覆盖。
   - 结果：测试数从 **330** 调整为 **327**，覆盖重点保持不变。

3. **本地模型配置误提交风险**
   - 根因：真实模型联调需要在本地配置 OpenAI 兼容 `base_url`/`model_name`/key。
   - 修复：`.gitignore` 增加 `config/local-openai-compatible.json`，避免提交本地接口地址和密钥。

### 真实模型联调发现

1. **模型接口可用**
   - `select_worker_profile` 最小探针成功返回 JSON，包含 `profile`/`reason`。
   - 平台 API 联调成功产生 `program_compiled`，`planner_source=['llm', 'llm']`，说明真实模型已参与 worker/profile 决策和结构化 program 选择。

2. **API key 配置优先级容易踩坑**
   - 当前 `model_adapter._resolve_api_key()` 优先读取 `api_key_env`，只有 `api_key_env` 为空时才读取 literal `api_key`。
   - 如果配置同时写了 `api_key` 和 `api_key_env="ATTACK_AGENT_API_KEY"`，但环境变量未设置，CLI 会报 `ValueError: environment variable ATTACK_AGENT_API_KEY not set`。
   - 临时联调方式：在启动进程前把本地配置中的 key 注入同名环境变量；长期建议二选一：要么只用环境变量，要么清空 `api_key_env` 后使用本地 literal key。

3. **OpenAI 兼容接口对较长输出参数敏感**
   - `max_tokens=1024` 时，`choose_program` 曾触发 `model_adapter_connection_error`。
   - 将 `max_tokens` 临时降到 `256`、`timeout_seconds` 提高到 `60` 后，`choose_program` 和平台 4-cycle 联调均成功。
   - 建议本地模型联调配置：
     - `max_tokens`: 256
     - `timeout_seconds`: 60
     - `max_retries`: 0（调试时避免重试掩盖真实失败点）

4. **当前 `127.0.0.1:8000` 未提供可连接靶场服务**
   - shell 侧 `Invoke-WebRequest http://127.0.0.1:8000/` 返回无法连接远程服务器。
   - 因此本次只能确认“模型 + AttackAgent 调度链路”正常，不能确认“模型 + 真实 localhost:8000 靶场解题”。

### 验证结果

```bash
python -m unittest tests.test_platform_flow -v
# Ran 13 tests in ~14s, OK

python -m unittest discover tests/ -v
# Ran 327 tests in ~36s, OK
```

真实模型平台联调摘要：
```text
ok=True
program_compiled_count=2
planner_sources=['llm', 'llm']
outcome_count=2
candidate_flags=0
```
