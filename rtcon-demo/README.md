# RTCON AVDTP Demo

最小 RTCON 机制演示：被 RTOS 上下文阻塞的函数，通过**静态分析 + 追踪 + 约束求解 + 重跑**闭环自动打通。

## 快速开始

```bash
python3 demo/workflow/run_demo.py
```

一键完成：CodeQL 事实提取 → 分析计划 → 源码插桩 → harness 生成 → 编译 → 第一轮（阻塞）→ 求解 → 第二轮（crash）。

## 原理

目标函数是 Zephyr 蓝牙 AVDTP 协议栈中提取的 `avdtp_process_configuration`，有三层上下文门控：

| 行号 | 条件 | 阻塞原因 |
|------|------|----------|
| 135 | `msg_type == BT_AVDTP_CMD` | 消息类型不对 |
| 141 | `sep == NULL \|\| callback == NULL` | 缺少 SEP 端点 / 回调函数 |
| 144 | `sep->state == AVDTP_STREAMING` | SEP 状态不对 |

Bug 在 `net_buf_simple_pull_u8`（第 60-61 行）：先 `len -= 1` 再 `*data++`，没有下溢检查。harness 提供 1 字节的 buffer 但逻辑长度也为 1 时，第二次 `pull_u8` 会越界读取。

### 第一轮

全零种子输入 harness。`msg_type == 0` 碰巧满足，但 `sep` 和 `callback` 都是 NULL —— 执行被第 141 行挡住。

```
RTCON_TRACE  branch  135  var=msg_type  actual=0  expected=0  passed=1
RTCON_TRACE  branch  141  var=sep       actual=0x0              passed=0
RTCON_RESULT BUG_NOT_REACHED (blocked at lines ['141'])
```

### 求解

`solve.py` 读取 trace，对照 `analysis.json` 匹配失败分支，构建 Z3 约束，输出 `solution.json`：

```json
{
  "input_hex": "00070104",
  "input_fields": {
    "data[0]": {"value": 0,   "description": "msg_type = BT_AVDTP_CMD"},
    "data[1]": {"value": 7,   "description": "flags: LOOKUP | CALLBACK | SHORT"},
    "data[2]": {"value": 1,   "description": "buf.len = 1"},
    "data[3]": {"value": 4,   "description": "SEP id << 2 = 1 << 2"}
  }
}
```

### 第二轮

求解出的 hex `00070104` 输入 harness。三个分支全部通过，回调被调用，第二次 `net_buf_pull_u8` 触发 ASAN 栈缓冲区溢出。

```
RTCON_TRACE  branch  144  var=sep->state  actual=0  expected=4  passed=1
=================================================================
==...==ERROR: AddressSanitizer: stack-buffer-overflow
RTCON_RESULT BUG_REACHED (ASAN)
```

## 管线步骤

**Phase 1 — CodeQL 事实提取**  
`codeql/run_codeql.py` 对目标源码创建 CodeQL 数据库，运行 `avdtp_facts.ql` 提取参数、if 语句、函数调用、表达式等结构事实，输出 `facts.json`。

**Phase 2 — 生成分析计划**  
`make_analysis.py` 读取 `facts.json`，分类出 input_like（攻击者可控输入）、context_like（执行上下文）、critical_branches（需追踪的分支）、bug_markers（bug 触发点），输出核心数据契约 `analysis.json`。这一步模拟 LLM 的分析输出。

**Phase 3 — 源码插桩**  
`instrument.py` 读取 `analysis.json`，在原始源码的每个关键分支和 bug 标记前插入 `fprintf(stderr, ...)` 追踪钩子，输出 `avdtp_target_inst.c`。

**Phase 4 — 生成 harness**  
`generate_harness.py` 读取 `analysis.json` 和原始源码，自动推断目标函数的参数结构、callback 签名、SEP 查找机制，生成完整的 harness 程序（含 `LLVMFuzzerTestOneInput` 和 `main`），输出 `avdtp_harness.c`。

**Phase 5 — 编译**  
用 `cc -fsanitize=address` 编译 harness（内嵌插桩后的目标源码）。

**Phase 6 — 第一轮运行**  
全零种子 `0000000000` 输入 harness，trace 输出到 `trace_round1.log`。预期被上下文门控阻塞：`BUG_NOT_REACHED`。

**Phase 7 — 约束求解**  
`solve.py` 解析第一轮 trace 中的失败分支，对照 `analysis.json` 的 trace_vars 构建 Z3 约束，求解出能通过所有门控并触发 bug 的输入，输出 `solution.json`。

**Phase 8 — 第二轮运行**  
用求解出的 hex 输入 harness，所有分支通过，到达 bug 点触发 ASAN 栈溢出：`BUG_REACHED`。

## 文件结构

```
demo/
├── README.md
├── avdtp_case/
│   ├── avdtp_target.c                   # 被测目标（Zephyr AVDTP 提取）
│   └── zephyr_sources/                  # Zephyr 头文件 / 源文件依赖
├── workflow/
│   ├── run_demo.py                      # 一键编排全流程
│   ├── make_analysis.py                 # facts → analysis.json
│   ├── instrument.py                    # 源码插桩
│   ├── solve.py                         # trace → Z3 约束求解
│   ├── generate_harness.py              # analysis.json → harness.c
│   └── codeql/
│       ├── run_codeql.py                # CodeQL 流水线驱动
│       └── avdtp_facts.ql               # 结构事实查询
└── output/
    ├── .gitignore
    ├── analysis.json                    # 核心数据契约（手写，模拟 LLM 输出）
    ├── instrumented/
    │   └── avdtp_target_inst.c          # 插桩后的源码（生成）
    ├── codeql/
    │   ├── facts.json                   # CodeQL 原始事实（生成）
    │   └── avdtp-db/                    # CodeQL 数据库（生成）
    └── run/
        ├── avdtp_harness.c              # 生成的 harness
        ├── avdtp_harness                # 编译产物（ASAN）
        ├── trace_round1.log             # 第一轮 trace
        ├── trace_round2.log             # 第二轮 trace
        └── solution.json                # 求解结果
```

## 与 tips.md 要求的对应关系

| 要求 | 实现 |
|------|------|
| LLM + CodeQL 替代污点分析 | `analysis.json` 作为 LLM+CodeQL 输出契约 |
| LLM 源码插桩 | `instrument.py` 生成 C 源码追踪钩子 |
| SymCC 风格符号分析 | `solve.py` 基于 trace 的 Z3 约束求解 |

## v1 局限

- `analysis.json` 中的数据（trace_vars、context_mechanism、bug_trigger）是手写的，模拟 LLM 分析 CodeQL 事实后的输出。生产环境中这一步由 LLM 完成。
- `instrument.py` 是规则驱动的（根据 trace_vars 机械生成 fprintf），不是 LLM 生成的。
- `solve.py` 使用 Z3，未接入 SymCC。
- 上下文构造仍通过 `data[1]` 的标志位机制 —— 求解器的职责是自动算出正确的标志值，而非发明新的 harness 机制。
- 单轮求解，不做多轮迭代优化。
