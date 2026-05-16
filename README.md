# IoTSymDemo

这是一个围绕 RTOS / IoT 固件动态分析论文做最小可运行复现的实验仓库。

当前主线是基于 [CO3 论文](co3-demo/sec24-CO3.md) 实现一个最小化 CO3 demo，用 Python 版本先解释 trace、SVFG、Z3 分支翻转，再用 C 版 MiniIoT 演示源码级插桩。后续会参考 RTCON 论文实现一个类似的 `rtcon-demo`，用于理解 RTOS 内核函数级 fuzzing、上下文自适应生成和 crash 分类。

## 学习顺序

- [CO3 原理解析](co3-demo/Insights.md)
- [Z3 最简教程](co3-demo/minimal-co3/z3_learn.ipynb)
- [CO3 Python 最简原型](co3-demo/minimal-co3/co3.ipynb)
- [MiniIoT 源码级插桩 Demo 说明](co3-demo/src-demo/README.md)
- [RTC ON 论文材料](rtcon-demo/ndss26_rtcon.md)

## 目录结构

| 路径 | 作用 |
|---|---|
| `README.md` | 项目入口说明和推荐学习顺序 |
| `requirements.txt` | Python 依赖，当前主要是 `z3-solver` |
| `co3-demo/` | C 版 MiniIoT/CO3 演示集合，包含源码级 demo、原始固件和未来二进制级 demo 占位 |
| `co3-demo/DESIGN.md` | CO3 源码级 demo 的设计文档 |
| `co3-demo/Insights.md` | CO3 论文核心思路解析 |
| `co3-demo/sec24-CO3.md` | CO3 论文文本材料 |
| `co3-demo/minimal-co3/` | Python 最简 CO3 原理 demo，先从这里理解 trace、SVFG、Z3 分支翻转 |
| `co3-demo/firmware/` | 原始无插桩 MiniIoT 固件源码 |
| `co3-demo/src-demo/` | C 版 MiniIoT 源码级插桩 demo，生成和分析 JSONL trace |
| `co3-demo/bin-demo/` | 预留给未来二进制级 Qiling demo |
| `rtcon-demo/` | 预留给 RTC ON 风格 RTOS 函数级 fuzzing demo |
| `rtcon-demo/ndss26_rtcon.md` | RTC ON 论文文本材料 |

`co3-demo/minimal-co3/` 内部重点文件：

| 路径 | 作用 |
|---|---|
| `co3-demo/minimal-co3/device.py` | 模拟 MCU/固件端：具体执行协议逻辑并输出 CO3 trace |
| `co3-demo/minimal-co3/host.py` | 模拟 workstation/主机端：读取 trace，绑定 `EXTRACTED_SVFG`，用 Z3 求下一轮输入 |
| `co3-demo/minimal-co3/common.py` | 插桩 ID、分支 ID、函数 ID，以及“从固件编译期提取”的极简 SVFG 信息 |
| `co3-demo/minimal-co3/co3_trace.txt` | 设备端最近一轮输出的原始 trace |
| `co3-demo/minimal-co3/co3_log.txt` | 主机端解码 trace、构造约束和 Z3 model 的详细日志 |
| `co3-demo/minimal-co3/z3_learn.ipynb` | Z3 最小教程 notebook |
| `co3-demo/minimal-co3/co3.ipynb` | CO3 最小流程 notebook |

建议先运行 `co3-demo/minimal-co3/` 理解 CO3 的核心闭环：设备端输出 trace，主机端绑定 `EXTRACTED_SVFG`，Z3 求解下一轮输入。C 版 MiniIoT 的运行方式、JSONL trace 解读和测试用例说明请看 [co3-demo/src-demo/README.md](co3-demo/src-demo/README.md)。

## 当前范围

本版本已经包含 CO3 方向的两个层次：

- Python 最小版：用最少代码解释 CO3 的符号采集、SVFG 绑定、Z3 求解和分支翻转。
- C 版 MiniIoT：手工或 LLM 基于原始 C 源码加入 `sym_*` 记录点，然后运行测试输入并生成 JSONL trace。

`co3-demo/bin-demo/` 目前只是占位目录，后续可扩展为二进制级固件加载、外设模型和 Qiling hook 演示。

## 后续计划：RTC ON Demo

下一阶段会参考 [RTC ON 论文](rtcon-demo/ndss26_rtcon.md) 在 `rtcon-demo/` 下实现一个类似的最小 demo。目标不是完整复现论文系统，而是把核心机制做成可读、可跑、可观察的教学版本：

- 函数级 fuzzing：绕过完整协议流程，直接 fuzz RTOS/协议栈内部目标函数。
- 上下文自适应生成：当目标函数因为缺少状态、指针、结构体字段或比较条件被卡住时，动态生成最小上下文。
- load / indirect call sanitization：用 hook 思路避免无效上下文导致 fuzzing 过早崩溃。
- comparison/context generation：捕获比较操作数，生成候选上下文值，推动执行进入更深分支。
- crash 分类：区分高置信度真实 bug 和由缺失上下文导致的低置信度 crash。

推荐阅读顺序是：先用 CO3 demo 理解“trace + 主机分析 + 约束求解”的闭环，再进入 RTC ON demo 理解“函数级 fuzzing + 上下文生成”的闭环。
