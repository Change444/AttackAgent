# Conventions

项目特有编码规则和约束。这些是政策性规则，无法从代码推导但必须执行。

---

## Code Style

- 所有公共方法必须添加类型注解
- 数据结构使用 `dataclass(slots=True)`
- PEP 8 命名规范
- 类和公共方法添加简短 docstring（一行最多）；内联注释仅用于非显而易见的逻辑

## Testing Rules

- 测试覆盖率目标 > 80%（当前 327 个测试全部通过）
- 新模块合并前必须包含对应测试文件
- 测试命名：`test_{module}_{scenario}`
- 元数据回退路径必须保留在测试中（backward compatibility）
- 运行命令：`python -m unittest discover tests/`

## Security Constraints

- LightweightSecurityShell 在 runtime 执行前验证所有 TaskBundle
- Critical 级违规阻止执行；Warning 级违规仅记录
- SecurityConstraints 值从 SecurityConfig 直接获取——SecurityConstraints 类已删除（v4.1），SecurityConfig 直接作为 LightweightSecurityShell 约束源（禁止在业务逻辑中硬编码默认值）
- `step.parameters` 中 URL scope 必须匹配 `allowed_hostpatterns`——`_check_parameter_scope()` 强制此规则
- 参数优先级：`step.parameters` > metadata defaults > hardcoded defaults

## Backward Compatibility

- 元数据回退路径 `_consume_metadata` **已删除**（Phase 1 R3, v3.8）——原语无配置时返回 `_clean_fail` 干净失败
- 删除前：配置新增字段必须提供默认值，确保现有 JSON 文件仍可加载
- 删除前：公共方法签名不得删除，需变更时提供过渡期

## Dependency Policy

- stdlib-first：urllib、html.parser、json 为默认实现
- 可选包（openai、anthropic、sentence-transformers）通过惰性导入接入，不可用时返回 None 或回退
- 不得添加非 stdlib 的必需依赖

## Documentation Rule

- 文档描述架构决策和概念关系，不复制代码结构细节
- dataclass/enum/constant 变更时**不更新文档**——只更新源文件
- 文档仅在架构决策本身变更时才需更新
- 需要引用代码细节时，链接源文件而非复制定义