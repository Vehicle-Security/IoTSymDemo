# IoTSymDemo

这是一个基于 CO3 思路实现的最小化源码级插桩固件分析原型，用简单 JSONL 跟踪记录固件路径、分支条件和漏洞事件。

当前仓库重点是 `src-demo/`：一个可运行、可阅读、方便教学的 MiniIoT 源码级插桩 demo。

## 学习顺序

- [CO3 原理解析](Insights.md)
- [z3基本教程](minimal/z3_learn.py)
- [CO3 Python最简原型](minimal/README.md)
- [MiniIoT 源码级插桩 Demo 说明](src-demo/README.md)

## 目录结构

| 路径 | 作用 |
|---|---|
| `firmware/` | 原始无插桩 MiniIoT 固件源码 |
| `src-demo/` | 当前可运行的源码级插桩 demo |
| `bin-demo/` | 预留给未来二进制级 Qiling demo |

具体运行方式、trace 解读和测试用例说明请直接看 [src-demo/README.md](src-demo/README.md)。

## 当前范围

本版本只实现源码级插桩演示：手工或 LLM 基于原始 C 源码加入 `sym_*` 记录点，然后运行测试输入并生成 JSONL trace。

`bin-demo/` 目前只是占位目录，后续可扩展为二进制级固件加载、外设模型和 Qiling hook 演示。

## 可选：调用 GPT API 总结论文

如果已经设置 `OPENAI_API_KEY`，可以用 Responses API 基于论文文本生成一份新的总结：

```bash
export OPENAI_API_KEY=你的_key
python3 tools/summarize_with_gpt.py sec24-CO3.md -o Insights.gpt.md
```

默认模型可通过 `OPENAI_MODEL` 或 `--model` 覆盖：

```bash
OPENAI_MODEL=gpt-5.5 python3 tools/summarize_with_gpt.py sec24-CO3.md
```

这个脚本是可选工具，不影响 `src-demo/` 和 `minimal/` 的本地运行。
