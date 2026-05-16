# IoTSymDemo

这是一个基于 CO3 思路实现的最小化源码级插桩固件分析原型，用简单 JSONL 跟踪记录固件路径、分支条件和漏洞事件。

## 学习顺序

- [CO3 原理解析](Insights.md)
- [Z3 最简教程](minimal-co3/z3_learn.ipynb)
- [CO3 Python 最简原型](minimal-co3/co3.ipynb)
- [MiniIoT 源码级插桩 Demo 说明](co3-demo/src-demo/README.md)

## 目录结构

| 路径 | 作用 |
|---|---|
| `README.md` | 项目入口说明和推荐学习顺序 |
| `DESIGN.md` | 源码级 demo 的设计文档 |
| `Insights.md` | CO3 论文核心思路解析 |
| `sec24-CO3.md` | CO3 论文文本材料 |
| `requirements.txt` | Python 依赖，当前主要是 `z3-solver` |
| `minimal-co3/` | Python 最简 CO3 原理 demo，先从这里理解 trace、SVFG、Z3 分支翻转 |
| `co3-demo/` | C 版 MiniIoT/CO3 演示集合，包含源码级 demo、原始固件和未来二进制级 demo 占位 |
| `co3-demo/firmware/` | 原始无插桩 MiniIoT 固件源码 |
| `co3-demo/src-demo/` | C 版 MiniIoT 源码级插桩 demo，生成和分析 JSONL trace |
| `co3-demo/bin-demo/` | 预留给未来二进制级 Qiling demo |

`minimal-co3/` 内部重点文件：

| 路径 | 作用 |
|---|---|
| `minimal-co3/device.py` | 模拟 MCU/固件端：具体执行协议逻辑并输出 CO3 trace |
| `minimal-co3/host.py` | 模拟 workstation/主机端：读取 trace，绑定 `EXTRACTED_SVFG`，用 Z3 求下一轮输入 |
| `minimal-co3/common.py` | 插桩 ID、分支 ID、函数 ID，以及“从固件编译期提取”的极简 SVFG 信息 |
| `minimal-co3/co3_trace.txt` | 设备端最近一轮输出的原始 trace |
| `minimal-co3/co3_log.txt` | 主机端解码 trace、构造约束和 Z3 model 的详细日志 |
| `minimal-co3/z3_learn.ipynb` | Z3 最小教程 notebook |
| `minimal-co3/co3.ipynb` | CO3 最小流程 notebook |

建议先运行 `minimal-co3/` 理解 CO3 的核心闭环：设备端输出 trace，主机端绑定 `EXTRACTED_SVFG`，Z3 求解下一轮输入。C 版 MiniIoT 的运行方式、JSONL trace 解读和测试用例说明请看 [co3-demo/src-demo/README.md](co3-demo/src-demo/README.md)。

## 当前范围

本版本只实现源码级插桩演示：手工或 LLM 基于原始 C 源码加入 `sym_*` 记录点，然后运行测试输入并生成 JSONL trace。

`co3-demo/bin-demo/` 目前只是占位目录，后续可扩展为二进制级固件加载、外设模型和 Qiling hook 演示。
