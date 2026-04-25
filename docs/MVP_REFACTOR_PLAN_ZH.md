# AttackAgent 重构与 MVP 计划（中文更新版）

## 当前结论

这份计划文档最初提出的方向仍然成立：

- 平台路径是唯一主路径
- primitive adapter 是主要扩展机制
- 先做最小真实能力，再逐步扩大覆盖面
- 模型推理必须受 provider / runtime / state-graph 边界约束

但项目阶段已经比最初计划前进了一大步。

## 当前阶段事实

第一阶段“最小真实 primitive 闭环”已经完成：

- `http-request`
- `browser-inspect`
- `binary-inspect`
- `artifact-scan`

这四条都已经完成：

- 最小真实执行分支
- metadata fallback 保留
- integration-style 测试覆盖
- 当前状态文档同步

所以项目已经从“架构原型”进入“可运行平台骨架”阶段。

## 当前还没有完成的部分

当前平台仍然不是完整落地平台，主要缺口在：

- `EpisodeMemory` 仍是内存态，没有跨运行持久化
- `PatternGraph` / `RunJournal` 还没有真实 Web 可视化
- 4 个 primitive 仍然只是最小切片，不是完整环境能力
- 模型虽然已经有 reasoning 接口，但还没有进入真正依赖长期记忆和可观察性的增强阶段

## 当前推荐阶段排序

### 阶段 1：最小真实 primitive 闭环

状态：已完成

交付物：

- 平台主路径稳定
- 4 个最小真实 primitive 可运行
- fallback 保留
- integration-style 测试建立

### 阶段 2：让系统可积累

状态：下一阶段

重点：

- 为 `EpisodeMemory` 增加最小持久化能力
- 保持当前行为兼容，不把任务扩大成复杂知识库

交付物：

- 跨运行可保留的最小 episode memory
- 可验证的 retrieval 连续性

### 阶段 3：让系统可观察

状态：阶段 2 之后

重点：

- 为 `PatternGraph` 和 `RunJournal` 增加最小 Web 可视化
- 让平台运行链路可观察、可复盘、可调试

交付物：

- 最小可视化入口
- 可查看当前阶段、候选路径、运行日志和关键证据

### 阶段 4：让模型真正增值

状态：阶段 2 和阶段 3 之后

重点：

- 在持久化 memory 和可视化基础上增强 reasoning
- 让模型参与 profile 选择、program 排序、candidate ranking、恢复路径决策
- 保持受约束输出和 fallback

交付物：

- 受控的模型增强规划能力

### 阶段 5：谨慎扩展真实能力

状态：更后续

重点：

- 更完整 browser automation
- 更完整 binary analysis
- 更完整 artifact / forensics 路径
- 更复杂真实环境覆盖

交付物：

- 更广但仍可控的真实 solving 能力

## 当前遗留路径结论

旧的单代理路径已经不再是产品路径。

当前策略是：

- 对外只保留平台路径为 canonical path
- 清理 legacy 入口、旧 demo、旧测试
- 对仍被平台状态/记忆层复用的共享内部模块，先保留并重新定性，再逐步迁移

也就是说，当前不是“盲删所有旧文件”，而是“按依赖边界下线旧产品路径”。

## 当前最推荐的下一步

下一条最值得做的任务是：

- 先为 `EpisodeMemory` 做只读分析
- 锁定最小持久化切入点、最小测试入口和禁止触碰边界

这是项目从“可运行”迈向“可运营”的第一步。
