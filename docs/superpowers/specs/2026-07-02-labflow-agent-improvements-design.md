# LabFlow Agent 系统性改进设计

**日期：** 2026-07-02
**项目：** LabFlow Agent（pico / labflow-agent）
**作者：** brainstorming 会话产出
**状态：** 待用户审阅

---

## 1. 背景与现状总结

### 1.1 项目定位

LabFlow Agent 是一个**本地科学数据工作流助手**，专注于实验批次数据的质量控制（QC）。核心设计约束：零外部运行时依赖、XML 工具协议、文件持久化、安全沙箱。

### 1.2 架构概览

系统采用 **tool-calling agent loop** 模式：

```
用户提示 → CLI(cli.py) 构建 Pico 运行时 → Pico.ask()(runtime.py)
  → build_prompt_and_metadata()(prompt_prefix.py + memory.py + context_manager.py)
  → model_client.complete()(providers/clients.py)
  → parse() 解析 <tool>{JSON}</tool> 或 <final>text</final>
  → 工具调用走 ToolExecutor → LabFlow 工具函数
  → 循环直至：最终答案 / 步数上限 / 重试上限 / provider 错误
  → 后处理：写报告、存 session、发 workflow trace
```

### 1.3 现有优势

- **清晰的模块划分**：CLI → Runtime → Tools → Providers → Memory → Safety 各司其职
- **完善的安全边界**：路径逃逸防护（`resolve_in_workspace` 校验 `relative_to`）、只读模式、脚本白名单（`REGISTERED_SCRIPTS`）、密钥脱敏
- **零依赖**：仅用 Python 标准库，部署简单
- **测试覆盖**：21 个测试文件覆盖核心逻辑，全部用 `TemporaryDirectory` 隔离
- **上下文预算管理**：12K 字符渐进式截断
- **原子文件写入**：`atomic_write_json` 确保崩溃安全

### 1.4 已识别的改进点

经全量代码审阅，发现以下问题（按改进阶段归类）：

| # | 问题 | 严重度 | 所在阶段 |
|---|------|--------|----------|
| 1 | `agent/intent.py` 和 `agent/planner.py` 已实现但未接入运行时（死代码） | 中 | Phase 3 |
| 2 | `safety/guard.py` 的 `assert_raw_data_readonly` 定义但从未调用——只读保护仅靠提示词 | 高 | Phase 1 |
| 3 | 无 provider 调用重试/退避机制 | 高 | Phase 2 |
| 4 | 无流式输出支持 | 中 | Phase 4 |
| 5 | `tools.py` 中通用工具（run_shell, write_file, patch_file）对 LabFlow 是死代码 | 低 | Phase 1 |
| 6 | 报告中文硬编码与评估器强耦合 | 中 | Phase 3 |
| 7 | 无 CI/CD 管道 | 中 | Phase 4 |
| 8 | 无真实 LLM provider 的集成测试 | 中 | Phase 4 |
| 9 | `tool_executor.py` 过宽的 `Exception` 捕获吞掉安全违规 | 高 | Phase 1 |
| 10 | 兼容性垫片文件（`agent_loop.py`、`session_store.py`）冗余 | 低 | Phase 1 |
| 11 | 错误缺乏分类体系，全部为通用异常 | 中 | Phase 2 |
| 12 | 存储文件损坏时直接崩溃，无恢复机制 | 中 | Phase 2 |
| 13 | 上下文截断策略固定，不随意图调整 | 低 | Phase 3 |
| 14 | trace 缺乏系统级运行指标 | 低 | Phase 4 |

---

## 2. 改进组织策略

采用**方案 A：按层级渐进**——按依赖关系和风险等级分 4 个阶段推进，每阶段内部可并行。低风险先行，变更可增量验证。

| 阶段 | 主题 | 风险 | 关键产出 |
|------|------|------|----------|
| 1 | 清理与加固 | 低 | 死代码清理、安全断言接入、异常细化 |
| 2 | 健壮性提升 | 中 | provider 重试、错误分类、损坏恢复 |
| 3 | 架构完善 | 中高 | 规划器接入、工具分层、报告模板化 |
| 4 | 工程化补充 | 高 | CI/CD、集成测试、流式、可观测性 |

---

## 3. Phase 1：清理与加固 🧹

**目标：** 低风险、高确定性改动，为后续阶段打好地基。
**风险：** 低。仅影响导入路径和防御性逻辑，无用户可见行为变更（除安全违规模现在被程序化阻断）。

### 3.1 移除死代码与兼容垫片

| 项目 | 位置 | 改动 |
|------|------|------|
| 通用工具死代码 | `pico/tools.py` | `run_shell`、`write_file`、`patch_file` 三个通用工具的函数体和 schema 从未被 LabFlow 注册表使用。保留 `ToolSpec`/`ToolResult` 数据类和 `_BASE_TOOLS` 列表结构（作为未来扩展锚点），移除那三个工具的具体实现函数和 schema 条目。 |
| `agent_loop.py` 垫片 | `pico/agent_loop.py` | 仅 `from pico.runtime import Pico` 再导出。删除文件，全局搜索替换 `from pico.agent_loop import Pico` → `from pico.runtime import Pico`。 |
| `session_store.py` 垫片 | `pico/session_store.py` | 仅 `from pico.run_store import SessionStore` 再导出。删除文件，替换所有导入。 |

**影响范围：** 仅导入路径，无行为变更。测试中引用同步修改。

### 3.2 接入 `assert_raw_data_readonly`

`pico/safety/guard.py` 中已定义此函数但从未被调用。当前原始数据只读保护仅依赖系统提示词，LLM 可能忽略。

**改动方案：**
- 在 `pico/tool_executor.py` 的 `execute()` 方法中，对 `write_file` 和 `patch_file` 类工具，在执行前调用 `assert_raw_data_readonly(path, workspace)` 做路径检查
- 在 `pico/labflow_tools.py` 中所有可能写入文件路径的工具函数（如 `generate_report`）内，在写入前插入断言调用
- 若路径落在 `data/` 目录内，抛出 `SafetyViolationError`（新增异常类，继承 `Exception`）

**新增：** `pico/safety/__init__.py` 导出 `SafetyViolationError`。

### 3.3 细化过宽异常捕获

`pico/tool_executor.py` 当前 `except Exception` 捕获所有异常并转为 `ToolResult(success=False, ...)`，包括安全违规。

**改动方案：** 分三层捕获：
1. `SafetyViolationError` → 直接向上抛出（安全违规不应被静默吞掉）
2. `ToolExecutionError`（新增，覆盖已知的工具业务错误如文件不存在、CSV 解析失败等）→ 转为 `ToolResult(success=False, error=...)` 并记录到 trace
3. `Exception` → 转为 `ToolResult(success=False, error="Unexpected error: ...")` 并额外记一条 WARNING 到 trace，便于排查意外异常

在 `pico/labflow_tools.py` 中将已知的业务错误（文件缺失、CSV 格式错误、batch_id 无效等）改为抛出 `ToolExecutionError` 而非返回错误字符串。

### 3.4 清理测试引用

同步更新测试文件中因上述改动产生的导入路径变化，确保 `pytest` 全绿。

---

## 4. Phase 2：健壮性提升 🛡️

**目标：** 让系统"出错时不崩、能自愈、可追溯"。
**风险：** 中。涉及 provider 调用逻辑和存储层改动。

### 4.1 Provider 重试与退避

当前 `pico/providers/clients.py` 中所有 provider 一次失败即终止运行。

**改动方案：** 新增 `pico/providers/retry.py`，提供通用重试装饰器：

```python
@dataclass
class RetryConfig:
    max_retries: int = 3
    base_delay_ms: int = 500        # 首次退避基数
    max_delay_ms: int = 10000       # 退避上限
    retryable_errors: tuple = (     # 可重试的错误类型
        ConnectionError, TimeoutError,
    )
```

- 采用**指数退避 + 抖动**：`delay = min(base * 2^attempt + random_jitter, max_delay)`
- 仅对**网络类错误**（`ConnectionError`、`TimeoutError`、HTTP 429/5xx）自动重试
- **API 内容错误**（400 Bad Request、认证失败 401/403）不重试，直接抛出
- 重试过程记录到 workflow trace（`retry_attempt` 事件）
- `RetryConfig` 可通过 `config.py` 的环境变量覆盖（`PICO_MAX_RETRIES`、`PICO_RETRY_BASE_DELAY_MS`）

**零依赖约束：** 用 `time.sleep()` + `random.randint()` 实现退避，不引入新依赖。

### 4.2 错误分类体系

当前所有 provider 错误都是 `ModelProviderError`，所有工具错误都是通用 `Exception`。

**改动方案：** 在 `pico/` 下新增 `errors.py`，建立统一错误层次：

```
PicoError (base)
├── ModelProviderError
│   ├── ProviderConnectionError      # 网络/连接问题 (可重试)
│   ├── ProviderRateLimitError       # 429 限流 (可重试)
│   ├── ProviderAuthError            # 401/403 认证失败 (不可重试)
│   └── ProviderResponseError        # 其他 API 错误 (不可重试)
├── ToolExecutionError               # Phase 1 已定义
├── SafetyViolationError             # Phase 1 已定义
├── ContextBudgetExceededError       # 上下文超限
└── StepLimitExceededError           # 步数超限
```

- `clients.py` 中根据 HTTP 状态码和异常类型映射到具体子类
- `retry.py` 根据 `retryable_errors` 元组判断是否重试（`ProviderConnectionError` 和 `ProviderRateLimitError` 可重试）
- `runtime.py` 中的错误处理根据子类做差异化应对（认证错误直接终止并提示用户，限流错误自动重试）

### 4.3 工具执行异常隔离改进

补充 Phase 1 的异常处理改进：

**改动方案：**
- 新增 `ToolExecutionError` 的 `error_code` 字段（枚举：`FILE_NOT_FOUND`、`INVALID_BATCH_ID`、`CSV_PARSE_ERROR`、`PERMISSION_DENIED`、`SCRIPT_NOT_WHITELISTED`）
- 每个 `error_code` 对应一个用户友好的中文提示模板（如 `"批次 {batch_id} 不存在，请检查 data/ 目录"`）
- `ToolResult` 增加 `error_code` 字段，便于评估脚本按类别统计错误分布
- `workflow_trace.py` 在 trace 事件中记录 `error_code`，便于事后分析高频失败模式

### 4.4 Session/Run 存储的损坏恢复

当前 `RunStore` 和 `SessionStore` 读取 JSON 文件时，若文件损坏会直接抛出 `json.JSONDecodeError`。

**改动方案：**
- 在 `load()` 方法中捕获 `json.JSONDecodeError`
- 若损坏，将损坏文件重命名为 `<name>.corrupted.<timestamp>` 保留现场
- 返回空默认值（新 `Session` / 空 `Run` 对象）而非崩溃
- 记一条 WARNING 日志到 trace

---

## 5. Phase 3：架构完善 🏗️

**目标：** 让规划器能力真正发挥作用，模块边界更清晰。
**风险：** 中高。涉及核心运行时改动和模块重组。

### 5.1 Agent 规划器接入运行时

`pico/agent/intent.py` 和 `pico/agent/planner.py` 已实现意图检测和工具规划，但 `pico/runtime.py` 完全依赖 LLM 自主决定调用哪些工具。

**改动方案：** 在 `Pico.ask()` 循环中增加**可选的规划引导层**：

- 新增配置项 `use_planner: bool`（默认 `True`），可通过 CLI `--no-planner` 关闭
- 首轮调用 LLM 前，先走规划器：
  1. `intent.py` 检测用户意图 → 返回 `Intent` 枚举值
  2. `planner.py` 根据意图 + 可用 batch_id 生成 `ToolPlan`（有序工具调用列表）
  3. 将 `ToolPlan` 注入系统提示词的 `<suggested_plan>` 区段，作为"推荐步骤"给 LLM 参考
- **LLM 仍然自主决定**是否遵循计划——规划器是建议者而非指挥者
- 若 LLM 偏离计划（调用了不在计划中的工具），trace 中记录 `plan_deviation` 事件
- 保留 `--no-planner` 选项让高级用户回到纯 LLM 驱动模式

**好处：** 对简单查询，规划器可大幅减少 LLM 试错步数；对复杂查询，LLM 不受约束仍可灵活处理。

### 5.2 通用工具与 LabFlow 工具分层

当前 `pico/tools.py` 混合了通用工具基础设施和通用工具实现，`pico/labflow_tools.py` 混合了工具实现和工具注册。

**改动方案：** 拆分为三层结构：

```
pico/
├── tools/
│   ├── __init__.py          # 重导出 ToolSpec, ToolResult
│   ├── base.py              # ToolSpec, ToolResult 数据类（从 tools.py 移入）
│   ├── generic.py           # 通用工具实现（run_shell 等，Phase 1 已精简）
│   ├── labflow.py           # LabFlow 工具实现（从 labflow_tools.py 移入）
│   └── registry.py          # 工具注册表（从 tool_registry.py 移入）
├── tool_context.py          # 不变
├── tool_executor.py         # 不变
```

- 旧的 `tools.py`、`labflow_tools.py`、`tool_registry.py` 保留为**重导出垫片**，标记 `DeprecationWarning`，一个版本周期后移除
- `build_tool_registry()` 逻辑不变，只是文件位置迁移
- LabFlow 工具函数签名不变，仅文件搬家

**好处：** `tools/` 包成为独立关注点，为未来支持用户自定义工具注册铺路。

### 5.3 报告模板化

当前 `pico/labflow_tools.py` 中 `generate_report()` 的报告结构硬编码在 Python 代码中，中文标题直接写在函数体内，与 `evaluate_qc.py` 的 `REQUIRED_REPORT_SECTIONS` 强耦合。

**改动方案：**
- 新增 `pico/report_template.py`，将报告结构抽取为模板：

```python
REPORT_TEMPLATE = {
    "sections": [
        {"key": "data_overview", "title_zh": "数据概况", "title_en": "Data Overview"},
        {"key": "metadata_check", "title_zh": "metadata 检查", "title_en": "Metadata Check"},
        # ...
    ]
}
```

- `generate_report()` 从模板动态渲染标题，支持 `--lang zh/en` 切换
- `evaluate_qc.py` 的 `REQUIRED_REPORT_SECTIONS` 改为从模板的 `key` 列表自动生成，不再硬编码中文标题
- 向后兼容：默认 `--lang zh` 保持当前行为不变

**好处：** 解耦报告内容与评估逻辑，未来支持英文报告或自定义报告结构无需改评估脚本。

### 5.4 上下文管理策略改进

当前 `pico/context_manager.py` 按 `relevant_memory → history → memory → prefix` 顺序截断，策略固定。

**改动方案：**
- 将截断策略抽取为 `TruncationStrategy` 协议类：

```python
class TruncationStrategy(Protocol):
    def truncate(self, sections: dict[str, str], budget: int) -> dict[str, str]: ...
```

- 默认策略 `PriorityTruncation` 保留当前行为
- 新增 `SmartTruncation`：根据当前意图动态调整优先级（如 `explain_finding` 意图保留更多 history，`full_qc` 保留更多 prefix）
- `config.py` 新增 `PICO_TRUNCATION_STRATEGY` 环境变量（`priority` / `smart`，默认 `priority`）

---

## 6. Phase 4：工程化补充 ⚙️

**目标：** 把项目从"能跑的原型"推向"可维护的生产项目"。
**风险：** 高。涉及 CI 基础设施和运行时新能力（流式）。

### 6.1 CI/CD 管道

当前项目无任何 CI/CD。

**改动方案：** 新增 `.github/workflows/ci.yml`，触发条件为 push/PR 到 `main` 分支：

- **Job 1: lint** — 运行 `ruff check` 和 `ruff format --check`（已在 pyproject.toml 配置）
- **Job 2: test** — 矩阵跑 Python 3.10 / 3.11 / 3.12，运行 `pytest tests/ -v`
- **Job 3: safety** — 专门跑 `tests/test_labflow_guard.py`、`tests/test_safety_boundaries.py`、`tests/test_tools_safety.py`，确保安全边界不被破坏

### 6.2 集成测试框架

当前测试全部用 `FakeModelClient`，无任何真实 provider 集成测试。

**改动方案：**
- 新增 `tests/integration/` 目录，与单元测试隔离
- 引入 **provider 契约测试**：定义一组标准输入（如"列出 batch_001 的文件"），每个 provider 都应产出符合协议的 `<final>` 或 `<tool>` 响应
- 集成测试通过环境变量门控：仅当 `PICO_RUN_INTEGRATION=1` 且对应 API key 配置时才运行
- 新增 `tests/integration/test_openai_provider.py`、`test_anthropic_provider.py`、`test_ollama_provider.py`
- 每个测试用 `@pytest.mark.integration` 标记，`pytest` 默认跳过，CI 中单独 job 可选触发

**零外部依赖原则不变：** 集成测试仅用于验证，不加入 `dependencies`，dev 依赖也不变（仍只用 pytest + ruff）。

### 6.3 流式输出支持

当前所有 provider 用 `urllib.request` 同步请求，返回完整响应。

**改动方案：**
- 为 `ModelClient` 协议增加 `complete_stream()` 方法（与 `complete()` 并存，后者保留向后兼容）：

```python
def complete_stream(self, prompt: str, ...) -> Iterator[str]:
    """逐 token 流式返回。"""
```

- `providers/clients.py` 中：
  - **OpenAI/Anthropic compatible**：改用 `urllib.request` 的流式读取（设置 `stream: true`，逐行解析 SSE）
  - **Ollama**：原生支持流式（`"stream": true`），逐行解析 NDJSON
  - **Fake**：按字符 yield 模拟流式
- CLI 层：`pico` 一次性输出模式支持 `--stream` 标志，逐 token 打印到终端
- `runtime.py` 的 `ask()` 增加 `stream=False` 参数；流式模式下仍需等到响应完整才能解析 `<tool>`/`<final>`，因此**仅在最终答案阶段向用户流式展示**，工具调用阶段不流式

**注意：** 流式输出的复杂点在于 SSE/NDJSON 解析。需为每个 provider 写独立的响应行解析器，并用单元测试覆盖（用预录制的响应片段）。

### 6.4 可观测性增强

当前 trace 仅记录工具调用事件，缺乏系统级运行指标。

**改动方案：**
- 在 `workflow_trace.py` 中新增运行摘要事件 `run_summary`，包含：
  - 总步数、工具调用次数、provider 调用次数、重试次数
  - 各阶段耗时（intent 检测、规划、LLM 调用、工具执行）
  - context budget 使用峰值
  - 最终 token 估算
- 新增 `scripts/summarize_traces.py`：扫描 `traces/` 目录，聚合多个 batch 的运行指标，输出对比表
- 评估脚本 `evaluate_qc.py` 增加 `--with-runtime-metrics` 选项，从 trace 中提取运行时指标纳入评估报告

### 6.5 文档完善

- 新增 `CONTRIBUTING.md`：开发流程、测试运行、代码风格规范
- 新增 `CHANGELOG.md`：记录本次系统性改进的所有变更
- 更新 `README.md`：补充 `--no-planner`、`--stream`、`--lang` 等新选项的说明
- 将 `summary/` 中的中文设计文档与代码现状对齐（特别是规划器接入、工具拆分后的结构）

---

## 7. 跨阶段依赖与顺序约束

```
Phase 1 (清理与加固)
  ├─ 1.1 死代码清理  ← 独立
  ├─ 1.2 安全断言接入 ← 依赖 1.1（需 SafetyViolationError 定义后接入）
  ├─ 1.3 异常细化    ← 依赖 1.2（SafetyViolationError 已定义）
  └─ 1.4 测试同步    ← 依赖 1.1–1.3 全部完成

Phase 2 (健壮性提升)
  ├─ 2.2 错误分类    ← 依赖 Phase 1（复用 SafetyViolationError、ToolExecutionError）
  ├─ 2.1 重试机制    ← 依赖 2.2（根据错误子类判断可重试性）
  ├─ 2.3 异常隔离改进 ← 依赖 2.2（error_code 体系）
  └─ 2.4 损坏恢复    ← 独立

Phase 3 (架构完善)
  ├─ 5.1 规划器接入  ← 独立（但建议在 Phase 1/2 稳定后进行）
  ├─ 5.2 工具分层    ← 依赖 Phase 1（1.1 已清理 tools.py 死代码）
  ├─ 5.3 报告模板化  ← 独立
  └─ 5.4 上下文策略  ← 独立

Phase 4 (工程化补充)
  ├─ 6.1 CI/CD       ← 独立，可尽早建立
  ├─ 6.2 集成测试    ← 依赖 Phase 2（provider 错误分类已稳定）
  ├─ 6.3 流式输出    ← 独立，但建议在 Phase 2 后
  ├─ 6.4 可观测性    ← 依赖 Phase 3（trace 事件已含规划器事件）
  └─ 6.5 文档完善    ← 最后进行，汇总所有改动
```

---

## 8. 不在本次范围内（YAGNI）

以下事项经评估后**不纳入**本次改进，避免过度设计：

- **多级 delegate 嵌套**：当前 max depth=1 已满足需求，不扩展
- **数据库持久化**：文件持久化对当前规模足够，不引入 SQLite
- **Web UI**：项目定位为本地 CLI 工具，不增加 Web 界面
- **多语言运行时**：保持纯 Python，不引入其他语言绑定
- **异步 provider**：当前同步模型足够，引入 asyncio 会大幅增加复杂度且与零依赖约束冲突
- **向量检索 memory**：当前 `LayeredMemory` 的关键词召回足够，向量检索需引入 embedding 依赖

---

## 9. 验收标准

每个阶段完成后的验收标准：

| 阶段 | 验收标准 |
|------|----------|
| Phase 1 | `pytest` 全绿；`ruff check` 无警告；`grep -r "agent_loop\|session_store"` 无残留导入；安全违规路径被程序化阻断 |
| Phase 2 | provider 网络错误自动重试 3 次后仍失败才终止；存储文件损坏时自愈而非崩溃；trace 含错误分类信息 |
| Phase 3 | `--no-planner` 模式与原行为一致；`--lang en` 产出英文报告且评估通过；工具导入路径迁移后测试全绿 |
| Phase 4 | CI 在 push/PR 上自动运行；集成测试在 `PICO_RUN_INTEGRATION=1` 时可运行；`--stream` 模式逐 token 输出；`run_summary` 事件出现在 trace 中 |

---

## 10. 后续步骤

本设计文档经用户审阅通过后，将调用 `superpowers:writing-plans` 技能，为每个阶段生成详细的实施计划（含具体文件改动、测试用例、验证步骤）。
