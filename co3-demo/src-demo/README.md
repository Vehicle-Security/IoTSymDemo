# MiniIoT 源码级插桩 Demo

这个目录演示一件事：**不真正做完整符号执行，也能先用很小的源码插桩，把固件运行时走过的路径记录下来**。

可以把它理解成给 C 程序加“行车记录仪”：

1. 输入是什么字节。
2. 程序做了哪些判断。
3. 判断结果是真还是假。
4. 进入了哪个协议处理函数。
5. 有没有碰到越界写这类 bug。

最后这些信息会写成 `traces/*.trace.jsonl`，Python 脚本再读取它们做分析。

## 文件分工

| 文件 | 作用 |
|---|---|
| `../firmware/miniiot.c` | 原始固件代码，不带插桩，像真实目标程序 |
| `miniiot_instrumented.c` | 手工插桩后的固件代码，逻辑基本相同，但多了记录 trace 的调用 |
| `sym_iot.h` / `sym_iot.c` | 插桩运行时，负责把事件写成 JSONL |
| `run.py` | 生成测试用例、编译、运行、分析 |
| `analysis.py` | 读取 trace，统计 handler、branch、bug、返回值 |
| `testcases/` | 输入样本，每个样本一个 `input.bin` |
| `traces/` | 运行后生成的路径记录 |

## 快速运行

在仓库根目录执行：

```bash
python3 src-demo/run.py gen
python3 src-demo/run.py build
python3 src-demo/run.py run-all
python3 src-demo/run.py analyze 009_write_config_oob
```

如果最后看到 `Status: PASS`，说明测试用例的实际运行结果符合 `meta.json` 里的预期。

## MiniIoT 协议长什么样

每个输入文件是一包 MiniIoT 数据：

```text
offset  含义
0       magic0，必须是 0xA5
1       magic1，必须是 0x5A
2       version，必须是 0x01
3       msg_type，消息类型
4       flags，标志位
5       session_id，会话 ID
6       payload_len，payload 长度
7       header_checksum，前 7 个字节的校验和
8..     payload
最后    payload_checksum，payload 校验和
```

固件先检查包头，再根据 `msg_type` 进入不同处理逻辑：

| msg_type | 处理函数含义 |
|---|---|
| `0x01` | `HELLO`，握手 |
| `0x02` | `AUTH`，认证 |
| `0x03` | `WRITE_CONFIG`，写配置 |

## 插桩到底加了什么

原始代码里可能只有这样的判断：

```c
if (buf[0] != MAGIC0) {
    return RET_ERR_MAGIC0;
}
```

插桩版会多记录两类信息：

```c
ok = buf[0] == MAGIC0;
sym_cmp_u8("magic0", "buf[0]", buf[0], "==", "0xa5", MAGIC0, ok);
sym_branch("magic0_ok", "buf[0] == 0xa5", ok);
if (!ok) {
    return trace_return(RET_ERR_MAGIC0);
}
```

这里的意思是：

- `sym_cmp_u8` 记录“哪个字节和哪个常量比较，实际值是多少”。
- `sym_branch` 记录“这个分支最后走了真还是假”。
- `trace_return` 记录函数最后返回了什么错误码。

这些记录不会改变固件的核心逻辑，只是把运行过程写出来。

## 一条 trace 怎么读

运行：

```bash
python3 src-demo/run.py run 009_write_config_oob
```

会生成：

```text
src-demo/traces/009_write_config_oob.trace.jsonl
```

这个文件每行都是一个 JSON 事件，例如：

```json
{"event":"handler","name":"WRITE_CONFIG"}
{"event":"mem_check","id":"config_index","array":"config","index":16,"limit":16,"ok":false}
{"event":"bug","id":"OOB_CONFIG_WRITE","detail":"config index out of bounds"}
{"event":"result","ret":-100}
```

翻译成人话就是：

1. 程序进入了 `WRITE_CONFIG` 处理逻辑。
2. 它准备用 `index = 16` 写 `config` 数组。
3. `config` 只有 16 个元素，合法下标是 `0..15`。
4. 所以记录了 `OOB_CONFIG_WRITE`。
5. 最后返回 `-100`。

## 从第一个例子完整走一遍

先看最简单的测试用例：

```bash
python3 src-demo/run.py run 001_short_input
python3 src-demo/run.py analyze 001_short_input
```

这个用例的输入只有 3 个字节：

```text
A5 5A 01
```

它太短了，MiniIoT 协议至少需要 9 字节，所以程序会在第一个长度检查处返回。

对应代码在 `miniiot_instrumented.c`：

```c
trace_input(buf, len);

int ok = (int)(len >= 9);
sym_branch("len_min", "len >= 9", ok);
if (!ok) {
    return trace_return(RET_ERR_SHORT);
}
```

这段代码做了三件事：

1. `trace_input(buf, len)` 记录输入长度和每个输入字节。
2. `sym_branch("len_min", "len >= 9", ok)` 记录程序遇到了一个分支：`len >= 9`。
3. `trace_return(RET_ERR_SHORT)` 记录最终返回值 `-1`。

生成的 trace 是：

```json
{"event":"value_size","name":"input_len","value":3}
{"event":"input_byte","index":0,"value":165}
{"event":"input_byte","index":1,"value":90}
{"event":"input_byte","index":2,"value":1}
{"event":"branch","id":"len_min","expr":"len >= 9","taken":false}
{"event":"result","ret":-1}
```

逐行翻译：

| trace 事件 | 意义 |
|---|---|
| `value_size input_len = 3` | 输入长度是 3 |
| `input_byte index=0 value=165` | 第 0 个字节是 `0xA5` |
| `input_byte index=1 value=90` | 第 1 个字节是 `0x5A` |
| `input_byte index=2 value=1` | 第 2 个字节是 `0x01` |
| `branch len_min taken=false` | `len >= 9` 这个条件不成立 |
| `result ret=-1` | 返回 `RET_ERR_SHORT` |

这里说“符号”，指的是这些输入字节和输入长度都被当成“外部可控数据”记录下来了。完整 CO3 会把它们映射到符号变量；本 demo 先用 JSONL 把事实写出来，方便初学者肉眼理解路径。注意：当前实现是按协议检查点做高层记录，而不是 CO3 那样在每条指令／影子内存读写处自动插桩。

## Z3 会怎么处理这些信息

当前 demo 的 Z3 部分在 `analysis.py` 里，故意做得很小，只解析 `cmp_u8` 事件里形如 `buf[i] == 常量` 的比较。

也就是说，`001_short_input` 只有长度分支：

```json
{"event":"branch","id":"len_min","expr":"len >= 9","taken":false}
```

它没有 `cmp_u8`，所以当前简化版 Z3 不会从这个用例里构造字节约束。真正的 CO3 会把长度、分支和数据流都放进 SVFG；本 demo 先保留最容易看懂的字节比较。

再看第二个用例：

```bash
python3 src-demo/run.py run 002_bad_magic
```

它会走到 `magic0` 检查：

```c
ok = buf[0] == MAGIC0;
sym_cmp_u8("magic0", "buf[0]", buf[0], "==", "0xa5", MAGIC0, ok);
sym_branch("magic0_ok", "buf[0] == 0xa5", ok);
if (!ok) {
    return trace_return(RET_ERR_MAGIC0);
}
```

trace 里会出现：

```json
{"event":"cmp_u8","id":"magic0","lhs":"buf[0]","lhs_val":0,"op":"==","rhs":"0xa5","rhs_val":165,"result":false}
{"event":"branch","id":"magic0_ok","expr":"buf[0] == 0xa5","taken":false}
```

这表示：

```text
实际输入：buf[0] = 0
目标条件：buf[0] == 0xA5
本次结果：false
```

`analysis.py` 中的简化 Z3 解析逻辑是：

```python
if lhs.startswith("buf[") and lhs.endswith("]"):
    index = int(lhs[4:-1])
    return self.buffer[index] == lhs_val
```

它会创建一组符号变量：

```python
buf_0, buf_1, buf_2, ...
```

然后把 trace 里的比较转成 Z3 约束。以当前实现来说，它记录的是“本次实际路径里的具体值”：

```text
buf_0 == 0
```

这可以验证当前路径是可满足的。完整 concolic execution 下一步会做“分支翻转”：

```text
当前走了 false：buf_0 != 0xA5
想探索另一边：buf_0 == 0xA5
Z3 求解得到：buf_0 = 0xA5
```

也就是把第 0 个字节改成 `0xA5`，程序就能越过 `magic0` 检查，继续探索后面的 `magic1`、`version`、checksum 等路径。

## 想修改输出，该改哪里

这个 demo 的“输出”分三层，每层修改的位置不一样。

### 1. 修改 trace 里记录什么

改 `miniiot_instrumented.c`。

例如想在长度检查失败时额外写一条事件：

```c
if (!ok) {
    sym_event("reject_short_input");
    return trace_return(RET_ERR_SHORT);
}
```

运行后 trace 会多一行：

```json
{"event":"event","name":"reject_short_input"}
```

适合用来标记协议阶段、错误原因、状态变化。

### 2. 修改 JSONL 的字段格式

改 `sym_iot.c`。

比如 `sym_branch` 当前输出：

```json
{"event":"branch","id":"len_min","expr":"len >= 9","taken":false}
```

如果想额外输出一个更适合教学的中文说明字段，就可以在 `sym_branch` 里加字段，例如：

```json
{"event":"branch","id":"len_min","expr":"len >= 9","taken":false,"note":"branch decision"}
```

注意：字段名改了以后，`analysis.py` 也可能要同步修改，否则分析脚本读不到新字段。

### 3. 修改 `analyze` 命令打印什么

改 `analysis.py`。

当前摘要来自：

```python
def summarize_trace(events: list[dict]) -> dict:
    return {
        "handlers": [...],
        "bugs": [...],
        "branches": ...,
        "comparisons": ...,
        "input_bytes": ...,
        "result": ...,
    }
```

如果想让分析结果打印所有分支，可以增加：

```python
"branch_details": [
    (e["id"], e["expr"], e["taken"])
    for e in events
    if e.get("event") == "branch"
]
```

然后在 `print_summary` 里打印：

```python
print("  branch details:")
for branch_id, expr, taken in summary["branch_details"]:
    print(f"    - {branch_id}: {expr} -> {taken}")
```

这样 `python3 src-demo/run.py analyze 001_short_input` 就能直接显示：

```text
branch details:
  - len_min: len >= 9 -> False
```

### 4. 修改测试用例期望结果

改 `testcases/<case_id>/meta.json`，或者改 `run.py` 里的 `generate_cases()` 后重新运行：

```bash
python3 src-demo/run.py gen
```

例如某个用例期望触发 `WRITE_CONFIG`，就检查：

```json
"expect": {
  "handler": "WRITE_CONFIG",
  "bug": null,
  "ret": 0
}
```

`analysis.py` 会拿 trace 里的实际 handler、bug、ret 和这里比较。

## 为什么 `009_write_config_oob` 能触发 bug

`WRITE_CONFIG` 的 payload 里：

```text
payload[0] = 要写入 config 的下标
payload[1] = 要写入的值
```

测试用例 `009_write_config_oob` 让：

```text
payload[0] = 0x10，也就是十进制 16
```

但 C 语言数组：

```c
uint8_t config[16];
```

只有 `config[0]` 到 `config[15]`。下标 `16` 越界，所以插桩版记录 bug。

## 目前代码做了哪些简化

为了让初学者更容易顺着代码读，`miniiot_instrumented.c` 里保留了三个小辅助函数：

| 函数 | 用途 |
|---|---|
| `trace_input` | 统一记录输入长度和每个输入字节 |
| `trace_return` | 统一记录返回值，然后返回 |
| `sym_mem_check` | 在数组写入前记录下标是否合法 |

`WRITE_CONFIG` 的核心流程现在是线性的：

```c
mem_ok = index < CONFIG_SIZE;
sym_mem_check(..., mem_ok);
if (!mem_ok) {
    sym_bug(...);
    return trace_return(RET_ERR_BUG_OOB);
}
ctx->config[index] = value;
return trace_return(RET_OK);
```

这比“先进入一个特殊分支，再在里面判断是否越界”更接近人脑读代码的顺序。

## 一个教学上的小约定

真实设备通常会先收到 `AUTH` 包，再收到 `WRITE_CONFIG` 包，同一个上下文会保存“已经认证”的状态。

这个 demo 为了让每个测试用例都只是一个 `input.bin`，运行时每次都会创建新的上下文。因此插桩版约定：

```text
flags 的最高位 0x80 表示：模拟已经认证
```

这只是为了让单包测试能覆盖 `WRITE_CONFIG` 的成功路径和越界路径，不是 MiniIoT 协议本身必须这么设计。

## 下一步怎么学习

建议按这个顺序读：

1. 先读 `../firmware/miniiot.c`，只理解协议检查和三个消息类型。
2. 再读 `miniiot_instrumented.c`，观察每个关键判断旁边多了哪些 `sym_*` 调用。
3. 运行一个测试用例，看 `traces/*.jsonl` 是否能和 C 代码的执行路径对上。
4. 修改 `testcases/*/input.bin` 或 `run.py` 里的样本，再观察 trace 如何变化。
