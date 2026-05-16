


````markdown
# DESIGN

## 1. Project Goal

This project is a minimal prototype for a **CO3-like firmware analysis workflow**.

The current implementation focuses on reproducing the **symbolic information collection** part of CO3:

1. Write a small C firmware-like protocol handler.
2. Use source-level instrumentation to mark the packet buffer as symbolic input.
3. Run the instrumented firmware concretely on protocol testcases.
4. Emit JSONL traces for symbolic ranges, symbolic memory reads/writes, branch outcomes, handler entry, bug reports, and program results.
5. Analyze the traces on the workstation side to understand the concrete path and the symbolic-relevant facts needed for later constraint construction.

In the CO3 paper, firmware executes concretely on the MCU and reports only runtime values that the workstation needs to build symbolic constraints. This demo mirrors that idea in a host-side executable:

- the input file buffer is treated as CO3's designated symbolic buffer;
- `mark_symbolic` corresponds to the monitor symbolizing that buffer and reporting its address/range;
- `inst_load` and `inst_store` approximate CO3's MCU-side symbolic-state tracking for RAM and only report memory operations relevant to symbolic data;
- `inst_branch` corresponds to CO3's pass-to-solver reporting by recording the concrete branch direction and operands;
- the JSONL trace stands in for CO3's serial/UART traffic to the workstation.

This version intentionally does not implement CO3's full compiler-generated SVFGs, real MCU execution, UART transport, byte-accurate shadow memory, interrupt handling, or automatic solver-driven input generation.

This repository intentionally keeps the first version small and easy to modify.

Future work will add a **binary-level Qiling demo**, but that is not part of the first implementation.

---

## 2. Repository Layout

The repository should use this layout:

```text
.
├── README.md
├── DESIGN.md
├── firmware/
│   └── miniiot.c
├── src-demo/
│   ├── miniiot_instrumented.c
│   ├── sym_iot.h
│   ├── sym_iot.c
│   ├── build.sh
│   ├── run.py
│   ├── analysis.py
│   ├── out/
│   ├── traces/
│   └── testcases/
│       ├── 001_short_input/
│       │   ├── input.bin
│       │   └── meta.json
│       ├── 002_bad_magic/
│       │   ├── input.bin
│       │   └── meta.json
│       ├── 003_bad_version/
│       │   ├── input.bin
│       │   └── meta.json
│       ├── 004_bad_checksum/
│       │   ├── input.bin
│       │   └── meta.json
│       ├── 005_hello_ok/
│       │   ├── input.bin
│       │   └── meta.json
│       ├── 006_auth_ok/
│       │   ├── input.bin
│       │   └── meta.json
│       ├── 007_write_config_without_auth/
│       │   ├── input.bin
│       │   └── meta.json
│       ├── 008_write_config_ok/
│       │   ├── input.bin
│       │   └── meta.json
│       └── 009_write_config_oob/
│           ├── input.bin
│           └── meta.json
└── bin-demo/
    └── README.md
````

Generated directories:

text

```text
src-demo/out/
src-demo/traces/
```

These may be created automatically by scripts.

---

## 3. Directory Responsibilities

### 3.1 `firmware/`

`firmware/` contains the clean original firmware source.

text

```text
firmware/
└── miniiot.c
```

Rules:

- This directory contains the original target code.
- It must not contain instrumentation runtime.
- It must not include `sym_iot.h`.
- It should look like normal firmware-style C code.
- It is the input to source-level instrumentation.

The file:

text

```text
firmware/miniiot.c
```

is the canonical uninstrumented MiniIoT firmware.

---

### 3.2 `src-demo/`

`src-demo/` contains the entire source-level demo.

text

```text
src-demo/
├── miniiot_instrumented.c
├── sym_iot.h
├── sym_iot.c
├── build.sh
├── run.py
├── analysis.py
├── out/
├── traces/
└── testcases/
```

Responsibilities:

- Store the LLM/manual instrumented source file.
- Store the source-level instrumentation runtime.
- Build the original and instrumented binaries for comparison.
- Generate testcases.
- Run testcases.
- Emit traces.
- Perform simple trace analysis.

Important files:

|File|Purpose|
|---|---|
|`miniiot_instrumented.c`|Instrumented version of `firmware/miniiot.c`|
|`sym_iot.h`|Instrumentation API declarations|
|`sym_iot.c`|Instrumentation runtime, JSONL trace writer|
|`build.sh`|Builds source-level demo binaries|
|`run.py`|Unified Python entrypoint for testcase generation, running, and analysis|
|`analysis.py`|Trace summarizer and optional simple satisfiability checker|
|`testcases/`|Protocol-level input cases|
|`out/`|Generated binaries|
|`traces/`|Generated JSONL traces|

The source-level demo should be runnable only through files under `src-demo/`.

---

### 3.3 `bin-demo/`

`bin-demo/` is reserved for the future binary-level demo.

Current content:

text

```text
bin-demo/
└── README.md
```

The current source-level implementation must not depend on `bin-demo/`.

Future `bin-demo/` may contain:

text

```text
bin-demo/
├── README.md
├── run_qiling.py
├── hooks.py
├── memory_map.py
├── firmware-bin/
│   └── miniiot.elf
├── models/
│   ├── uart.py
│   └── flash.py
├── testcases/
└── traces/
```

Meaning:

text

```text
src-demo = source-level instrumentation demo
bin-demo = future binary-level Qiling demo
```

---

## 4. MiniIoT Protocol

The first firmware target implements a small artificial protocol called **MiniIoT**.

The packet format is:

text

```text
offset  size  field
0       1     magic0
1       1     magic1
2       1     version
3       1     msg_type
4       1     flags
5       1     session_id
6       1     payload_len
7       1     header_checksum
8       N     payload
8 + N   1     payload_checksum
```

Minimum packet length:

text

```text
9 bytes
```

Header size without payload:

text

```text
8 bytes
```

Checksum rules:

text

```text
header_checksum = sum(bytes[0..6]) & 0xff
payload_checksum = sum(payload[0..payload_len-1]) & 0xff
```

Constants:

c

```c
#define MAGIC0  0xA5
#define MAGIC1  0x5A
#define VERSION 0x01

#define MSG_HELLO        0x01
#define MSG_AUTH         0x02
#define MSG_WRITE_CONFIG 0x03
```

Supported message types in version 1:

|Type|Name|Description|
|---|---|---|
|`0x01`|`HELLO`|Basic handshake|
|`0x02`|`AUTH`|Authenticate using a small payload|
|`0x03`|`WRITE_CONFIG`|Write one byte into a config array|

---

## 5. Firmware Behavior

The firmware should maintain a small context:

c

```c
typedef struct {
    uint8_t authenticated;
    uint8_t session_id;
    uint8_t config[16];
} iot_ctx_t;
```

The top-level function should look like:

c

```c
int process_packet(iot_ctx_t *ctx, const uint8_t *buf, size_t len);
```

The program entry point should:

1. Read an input file.
2. Initialize a context.
3. Call `process_packet`.
4. Return normally.

Suggested CLI for original firmware:

bash

```bash
./src-demo/out/miniiot_original src-demo/testcases/005_hello_ok/input.bin
```

Suggested CLI for instrumented firmware:

bash

```bash
./src-demo/out/miniiot_instrumented \
  src-demo/testcases/009_write_config_oob/input.bin \
  src-demo/traces/009_write_config_oob.trace.jsonl
```

---

## 6. Message Semantics

### 6.1 Common Validation

`process_packet` should perform these checks:

1. Input length must be at least 9.
2. `magic0 == 0xA5`.
3. `magic1 == 0x5A`.
4. `version == 0x01`.
5. `payload_len` must fit inside the packet.
6. Header checksum must match.
7. Payload checksum must match.
8. Dispatch by `msg_type`.

Example validation order:

text

```text
len >= 9
buf[0] == MAGIC0
buf[1] == MAGIC1
buf[2] == VERSION
8 + payload_len < len
header_checksum valid
payload_checksum valid
switch msg_type
```

---

### 6.2 `HELLO`

Message type:

c

```c
#define MSG_HELLO 0x01
```

Payload:

text

```text
payload_len == 0 or payload_len == 1
```

Behavior:

- If payload length is 0, accept.
- If payload length is 1, use `payload[0]` as a feature byte.
- If `(flags & 0x01) != 0`, set `ctx->session_id = session_id`.
- Return success.

This creates branch conditions on:

- `payload_len`
- `flags`

---

### 6.3 `AUTH`

Message type:

c

```c
#define MSG_AUTH 0x02
```

Payload:

text

```text
payload[0] = user_id
payload[1] = token0
payload[2] = token1
payload[3] = token2
```

Require:

text

```text
payload_len >= 4
```

Authentication succeeds if:

text

```text
user_id == 0x42
token0 == 0x13
token1 == 0x37
token2 == (session_id ^ 0x5a)
```

On success:

c

```c
ctx->authenticated = 1;
ctx->session_id = session_id;
```

On failure:

c

```c
ctx->authenticated = 0;
```

This creates path constraints involving:

- equality comparisons;
- XOR expression;
- multiple payload bytes.

---

### 6.4 `WRITE_CONFIG`

Message type:

c

```c
#define MSG_WRITE_CONFIG 0x03
```

Payload:

text

```text
payload[0] = index
payload[1] = value
```

Require:

text

```text
payload_len >= 2
```

Expected intended behavior:

c

```c
if (!ctx->authenticated) {
    reject;
}

if (index < 16) {
    ctx->config[index] = value;
}
```

For demo purposes, the instrumented firmware should expose a bug condition around out-of-bounds config write.

The original code may intentionally contain a bug such as:

c

```c
if (index <= 16) {
    ctx->config[index] = value;
}
```

This is an off-by-one bug because valid indexes are:

text

```text
0..15
```

Bug ID:

text

```text
OOB_CONFIG_WRITE
```

The instrumentation should report this bug when:

text

```text
index >= 16
```

or at least when:

text

```text
index == 16
```

depending on the implementation.

---

## 7. Source Instrumentation Design

The instrumented source file:

text

```text
src-demo/miniiot_instrumented.c
```

is derived from:

text

```text
firmware/miniiot.c
```

It should be functionally similar, but it adds calls to `sym_iot`.

The instrumentation should reproduce CO3's collection-side behavior at source level:

1. Mark the testcase input buffer as a symbolic range.
2. Route symbolic-relevant byte reads through `sym_read_u8`, which reports `load` events when the address is symbolic.
3. Report branch outcomes and concrete operands through `inst_branch`.
4. Report symbolic-relevant stores through `inst_store`, propagating symbolic state into the written address.
5. Record message handler entry.
6. Report explicit bug conditions.
7. Record the final program result.

Checksum validation, authentication checks, payload length checks, and config-index checks are all represented as branch events with concrete operands. In CO3 terms, these events are the demo's lightweight substitute for the runtime values consumed by workstation-side SVFG construction.

The instrumentation does not need to implement a full symbolic execution engine. It only needs to emit enough structured trace data so `analysis.py` or `run.py analyze` can show useful path information and demonstrate that CO3-style symbolic collection is happening.

---

## 8. `sym_iot` Runtime

### 8.1 Files

text

```text
src-demo/sym_iot.h
src-demo/sym_iot.c
```

### 8.2 Purpose

`sym_iot` is a tiny source-level instrumentation runtime.

It should:

- open a trace file;
- write one JSON object per line;
- flush after writes if useful;
- close the file at the end;
- provide simple helper APIs for recording CO3-style runtime facts.

Trace format:

text

```text
JSONL
```

That means each line is a complete JSON object.

Example:

json

```json
{"event":"symbolic_range","addr":140732774825600,"len":11}
{"event":"branch","taken":true,"lhs":165,"rhs":165,"op":"=="}
{"event":"bug","id":"OOB_CONFIG_WRITE","detail":"config index out of bounds"}
```

---

### 8.3 Minimal API

`sym_iot.h` should expose APIs similar to:

c

```c
#ifndef SYM_IOT_H
#define SYM_IOT_H

#include <stddef.h>
#include <stdint.h>

void sym_init(const char *trace_path);
void sym_close(void);

void sym_input_byte(size_t index, uint8_t value);

void sym_event(const char *name);
void sym_handler(const char *name);

void mark_symbolic(uintptr_t addr, uint32_t len);
void inst_load(uintptr_t addr, uint8_t value);
void inst_store(uintptr_t addr, uint8_t value);
void inst_branch(int taken, uint32_t lhs, uint32_t rhs, const char *op);

void sym_branch(const char *id, const char *expr, int taken);
void sym_cmp_u8(const char *id, const char *lhs, uint8_t lhs_val,
                const char *op, const char *rhs, uint8_t rhs_val,
                int result);

void sym_value_u8(const char *name, uint8_t value);
void sym_value_size(const char *name, size_t value);

void sym_mem_check(const char *id, const char *array_name,
                   size_t index, size_t limit, int ok);

void sym_bug(const char *id, const char *detail);
void sym_result(int ret);

#endif
```

The CO3-style path should use `mark_symbolic`, `inst_load`, `inst_store`, and `inst_branch`. The higher-level helpers such as `sym_input_byte`, `sym_branch`, `sym_cmp_u8`, and `sym_mem_check` may remain available for experiments, but they are not the canonical collection path for this demo.

The implementation can be simple and use `fprintf`.

---

### 8.4 Example JSONL Events

Symbolic input range:

json

```json
{"event":"symbolic_range","addr":140732774825600,"len":11}
```

Symbolic load:

json

```json
{"event":"load","addr":140732774825600,"value":165}
```

Branch:

json

```json
{"event":"branch","taken":true,"lhs":165,"rhs":165,"op":"=="}
```

Symbolic store:

json

```json
{"event":"store","addr":140732774825820,"value":171}
```

Handler:

json

```json
{"event":"handler","name":"AUTH"}
```

Bug:

json

```json
{"event":"bug","id":"OOB_CONFIG_WRITE","detail":"config index out of bounds"}
```

Result:

json

```json
{"event":"result","ret":0}
```

---

## 9. Instrumentation Points

The instrumented firmware should add trace events at these points. These points are chosen to mirror CO3's symbolic collection path: symbolize a designated input buffer, report symbolic memory interactions, and report branch decisions that the workstation can later turn into path constraints.

### 9.1 Designated Symbolic Input Buffer

At the start of `process_packet`, mark the whole testcase buffer as symbolic:

c

```c
mark_symbolic((uintptr_t)buf, (uint32_t)len);
```

This corresponds to CO3's designated-buffer input mode: the monitor knows the buffer address and tells the workstation that bytes in that range are symbolic.

This demo does not need to record every input byte separately. Concrete byte values are reported when symbolic bytes are read or compared along the executed path.

---

### 9.2 Symbolic Reads

Reads that may touch symbolic input should go through `sym_read_u8`:

c

```c
static uint8_t sym_read_u8(const uint8_t *ptr, size_t index) {
    uintptr_t addr = (uintptr_t)(ptr + index);
    uint8_t value = ptr[index];
    inst_load(addr, value);
    return value;
}
```

`inst_load` should emit a `load` event only when the address is inside a symbolic range. This approximates CO3's MCU-side shadow-memory check: concrete-only reads do not need to be sent to the workstation.

---

### 9.3 Branch Reporting

Each important condition should report:

- whether the branch was taken;
- the concrete left operand;
- the concrete right operand;
- the comparison operator.

Example length check:

c

```c
int ok = (int)(len >= 9);
inst_branch(ok, (uint32_t)len, 9, ">=");
if (!ok) {
    return trace_return(RET_ERR_SHORT);
}
```

Example magic check:

c

```c
uint8_t value0 = sym_read_u8(buf, 0);
ok = value0 == MAGIC0;
inst_branch(ok, value0, MAGIC0, "==");
if (!ok) {
    return trace_return(RET_ERR_MAGIC0);
}
```

In CO3 terms, this is the demo's pass-to-solver event: the workstation receives enough concrete runtime context to understand the branch taken by this concrete run.

---

### 9.4 Protocol Validation Branches

Instrument these validation points:

- `len >= 9`
- `buf[0] == MAGIC0`
- `buf[1] == MAGIC1`
- `buf[2] == VERSION`
- `8 + payload_len < len`
- `expected_header == actual_header`
- `expected_payload_checksum == actual_payload_checksum`

Checksum loops should read bytes through `sym_read_u8`, so the trace records the symbolic input bytes that influence checksum decisions.

The trace does not need a separate `cmp_u8` event for each comparison. `branch` events already carry the operator and concrete operands.

---

### 9.5 Message Dispatch

After validation, record the selected protocol handler:

c

```c
case MSG_HELLO:
    sym_handler("HELLO");
    ...

case MSG_AUTH:
    sym_handler("AUTH");
    ...

case MSG_WRITE_CONFIG:
    sym_handler("WRITE_CONFIG");
    ...

default:
    sym_handler("UNKNOWN");
    ...
```

Handler events make the trace easy to validate against testcase expectations while keeping branch and memory events focused on symbolic collection.

---

### 9.6 Authentication Checks

Authentication payload bytes should be read through `sym_read_u8`, then reported as branch decisions:

c

```c
uint8_t auth_user = sym_read_u8(payload, 0);
uint8_t auth_token0 = sym_read_u8(payload, 1);
uint8_t auth_token1 = sym_read_u8(payload, 2);
uint8_t auth_token2 = sym_read_u8(payload, 3);

int user_ok = auth_user == 0x42;
inst_branch(user_ok, auth_user, 0x42, "==");

uint8_t expected = session_id ^ 0x5a;
int token2_ok = auth_token2 == expected;
inst_branch(token2_ok, auth_token2, expected, "==");
```

The XOR-derived value is kept concrete on the MCU side, while the branch event reports the concrete comparison needed to describe the observed path.

---

### 9.7 Symbolic Store and Config Bounds Bug

Before writing into `ctx->config`, report the bounds decision:

c

```c
size_t index = sym_read_u8(payload, 0);
uint8_t value = sym_read_u8(payload, 1);

int mem_ok = index < CONFIG_SIZE;
inst_branch(mem_ok, (uint32_t)index, CONFIG_SIZE, "<");
if (!mem_ok) {
    sym_bug("OOB_CONFIG_WRITE", "config index out of bounds");
    return trace_return(RET_ERR_BUG_OOB);
}

inst_store((uintptr_t)(&ctx->config[index]), value);
ctx->config[index] = value;
return trace_return(RET_OK);
```

`inst_store` marks the destination byte symbolic in the demo runtime. This is the source-level counterpart of CO3 linking SVFGs through a memory write and a later read at the same address.

For safety, the instrumented firmware should report the out-of-bounds bug and skip the invalid write. This preserves deterministic demo behavior while still showing the bug condition.

---

### 9.8 Program Result

Every exit path should report its return code:

c

```c
static int trace_return(int ret) {
    sym_result(ret);
    return ret;
}
```

`result` events let `run.py analyze` compare the observed behavior with `meta.json`.

---

### 9.9 Scope Note

This demo intentionally implements a compact source-level subset of CO3's collection mechanism. It does not report every LLVM instruction, generate SVFGs, or maintain a byte-accurate symbolic expression in shadow memory. It does show the core idea needed for this repository: concrete firmware execution emits selective runtime facts that identify symbolic input flow, branch conditions, memory propagation, and bug reachability.

---

## 10. Testcase Design

Testcases live under:

text

```text
src-demo/testcases/
```

Each testcase has:

text

```text
input.bin
meta.json
```

Example:

text

```text
src-demo/testcases/009_write_config_oob/
├── input.bin
└── meta.json
```

---

### 10.1 `meta.json` Schema

Use this simple schema:

json

```json
{
  "id": "009_write_config_oob",
  "description": "Authenticated WRITE_CONFIG with index 16 triggers OOB config write",
  "protocol": "miniiot",
  "expect": {
    "handler": "WRITE_CONFIG",
    "bug": "OOB_CONFIG_WRITE",
    "ret": -100
  },
  "tags": ["write_config", "auth", "oob", "bug"]
}
```

Fields:

|Field|Meaning|
|---|---|
|`id`|Testcase ID, same as directory name|
|`description`|Human-readable description|
|`protocol`|Protocol name, currently `miniiot`|
|`expect.handler`|Expected handler name, or `null`|
|`expect.bug`|Expected bug ID, or `null`|
|`expect.ret`|Expected return value, or `null`|
|`tags`|List of tags|

---

### 10.2 Initial Testcases

Implement these initial testcases:

text

```text
001_short_input
002_bad_magic
003_bad_version
004_bad_checksum
005_hello_ok
006_auth_ok
007_write_config_without_auth
008_write_config_ok
009_write_config_oob
```

---

#### 001_short_input

Purpose:

text

```text
Input length is shorter than minimum packet size.
```

Expected:

json

```json
{
  "handler": null,
  "bug": null,
  "ret": -1
}
```

Tags:

json

```json
["length", "reject"]
```

---

#### 002_bad_magic

Purpose:

text

```text
Packet has incorrect magic bytes.
```

Expected:

json

```json
{
  "handler": null,
  "bug": null,
  "ret": -2
}
```

Tags:

json

```json
["magic", "reject"]
```

---

#### 003_bad_version

Purpose:

text

```text
Packet has valid magic but unsupported version.
```

Expected:

json

```json
{
  "handler": null,
  "bug": null,
  "ret": -3
}
```

Tags:

json

```json
["version", "reject"]
```

---

#### 004_bad_checksum

Purpose:

text

```text
Packet has bad header or payload checksum.
```

Expected:

json

```json
{
  "handler": null,
  "bug": null,
  "ret": -5
}
```

Tags:

json

```json
["checksum", "reject"]
```

---

#### 005_hello_ok

Purpose:

text

```text
Valid HELLO packet.
```

Expected:

json

```json
{
  "handler": "HELLO",
  "bug": null,
  "ret": 0
}
```

Tags:

json

```json
["hello", "valid"]
```

---

#### 006_auth_ok

Purpose:

text

```text
Valid AUTH packet.
```

Expected:

json

```json
{
  "handler": "AUTH",
  "bug": null,
  "ret": 0
}
```

Tags:

json

```json
["auth", "valid"]
```

---

#### 007_write_config_without_auth

Purpose:

text

```text
WRITE_CONFIG packet rejected because context is not authenticated.
```

Expected:

json

```json
{
  "handler": "WRITE_CONFIG",
  "bug": null,
  "ret": -20
}
```

Tags:

json

```json
["write_config", "auth", "reject"]
```

---

#### 008_write_config_ok

Purpose:

text

```text
WRITE_CONFIG packet with a valid index.
```

Expected:

json

```json
{
  "handler": "WRITE_CONFIG",
  "bug": null,
  "ret": 0
}
```

Tags:

json

```json
["write_config", "valid"]
```

---

#### 009_write_config_oob

Purpose:

text

```text
WRITE_CONFIG packet with index 16 triggers OOB bug.
```

Expected:

json

```json
{
  "handler": "WRITE_CONFIG",
  "bug": "OOB_CONFIG_WRITE",
  "ret": -100
}
```

Tags:

json

```json
["write_config", "oob", "bug"]
```

---

## 11. Important Note About Authentication State

Each program run processes one input file.

If `WRITE_CONFIG` requires previous authentication, there are two possible designs:

### Option A: One packet per input, but auth bypass through flag

For simplicity, allow a flag bit to pre-authenticate the context.

Example:

c

```c
if (flags & 0x80) {
    ctx->authenticated = 1;
}
```

Then `WRITE_CONFIG` testcases can be single-packet.

This is the recommended first-version design because it keeps testcases simple.

For example:

text

```text
008_write_config_ok
009_write_config_oob
```

can set:

text

```text
flags = 0x80
```

to start as authenticated.

---

### Option B: Multiple packets per input

The input file contains several packets:

text

```text
AUTH packet
WRITE_CONFIG packet
```

This is more realistic but more complex.

Do not implement this in the first version.

---

## 12. Recommended First-Version Choice

Use **Option A**.

Add this demo-only behavior:

c

```c
if (flags & 0x80) {
    ctx->authenticated = 1;
}
```

This should be clearly commented as test/demo behavior:

c

```c
/*
 * Demo shortcut:
 * If flags bit 7 is set, pre-authenticate the context.
 * This keeps each testcase as a single packet.
 */
if (flags & 0x80) {
    ctx->authenticated = 1;
}
```

This allows all testcases to be independent.

---

## 13. Build Design

The build script lives at:

text

```text
src-demo/build.sh
```

It should:

1. Compute repository root.
2. Create `src-demo/out`.
3. Create `src-demo/traces`.
4. Build original firmware.
5. Build instrumented firmware.

Example script:

bash

```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SRC_DIR="$ROOT_DIR/src-demo"
FW_DIR="$ROOT_DIR/firmware"

mkdir -p "\(SRC_DIR/out" "\)SRC_DIR/traces"

gcc -Wall -Wextra -O0 -g \
  "$FW_DIR/miniiot.c" \
  -o "$SRC_DIR/out/miniiot_original"

gcc -Wall -Wextra -O0 -g \
  -I "$SRC_DIR" \
  "$SRC_DIR/miniiot_instrumented.c" \
  "$SRC_DIR/sym_iot.c" \
  -o "$SRC_DIR/out/miniiot_instrumented"

echo "[OK] built:"
echo "  $SRC_DIR/out/miniiot_original"
echo "  $SRC_DIR/out/miniiot_instrumented"
```

Run:

bash

```bash
bash src-demo/build.sh
```

---

## 14. `run.py` Design

`src-demo/run.py` is the command-line entrypoint for the first version. `src-demo/analysis.py` may hold the trace-summary and optional satisfiability-check logic used by the `analyze` command.

It should support:

bash

```bash
python3 src-demo/run.py gen
python3 src-demo/run.py build
python3 src-demo/run.py run 005_hello_ok
python3 src-demo/run.py run-all
python3 src-demo/run.py analyze 009_write_config_oob
python3 src-demo/run.py clean
```

No additional `runner.py`, `trace.py`, or required solver module is needed in the first version.

---

### 14.1 Commands

#### `gen`

Generate all initial testcases.

bash

```bash
python3 src-demo/run.py gen
```

Creates:

text

```text
src-demo/testcases/*/input.bin
src-demo/testcases/*/meta.json
```

---

#### `build`

Run `src-demo/build.sh`.

bash

```bash
python3 src-demo/run.py build
```

---

#### `run CASE_ID`

Run one testcase with the instrumented binary.

bash

```bash
python3 src-demo/run.py run 009_write_config_oob
```

Input:

text

```text
src-demo/testcases/009_write_config_oob/input.bin
```

Output trace:

text

```text
src-demo/traces/009_write_config_oob.trace.jsonl
```

---

#### `run-all`

Run all testcases.

bash

```bash
python3 src-demo/run.py run-all
```

---

#### `analyze CASE_ID`

Analyze one trace.

bash

```bash
python3 src-demo/run.py analyze 009_write_config_oob
```

Should print:

text

```text
Case: 009_write_config_oob
Description: WRITE_CONFIG packet with index 16 triggers OOB config write.

Trace summary:
  branches: 9
  loads: 20
  stores: 0
  symbolic ranges: 1
  handlers:
    - WRITE_CONFIG
  bugs:
    - OOB_CONFIG_WRITE
  result: -100

Expectation:
  handler: WRITE_CONFIG
  bug: OOB_CONFIG_WRITE
  ret: -100

Status: PASS
Z3 not available: symbolic constraint check skipped
```

---

#### `clean`

Remove generated output:

bash

```bash
python3 src-demo/run.py clean
```

Should remove:

text

```text
src-demo/out/
src-demo/traces/
```

It should not remove testcases unless explicitly desired.

---

### 14.2 Internal Functions

`run.py` and `analysis.py` can split the command and trace-analysis functions like this:

python

View all

```python

def generate_cases() -> None:
    ...

def build() -> None:
    ...

def run_case(case_id: str) -> int:
    ...

def run_all() -> None:
    ...

# analysis.py
def load_jsonl(path: Path) -> list[dict]:
    ...

def analyze_case(case_id: str) -> bool:
    ...

def clean() -> None:
    ...

def main() -> None:
    ...
```

Run

---

### 14.3 Packet Generator

`make_packet` should implement the MiniIoT packet format:

python

View all

```python
def make_packet(msg_type: int, flags: int, session_id: int, payload: bytes) -> bytes:
    magic0 = 0xA5
    magic1 = 0x5A
    version = 0x01
    payload_len = len(payload)

    header_without_checksum = bytes([
        magic0,
        magic1,
        version,
        msg_type,
        flags,
        session_id,
        payload_len,
    ])

    header_checksum = sum(header_without_checksum) & 0xFF
    payload_checksum = sum(payload) & 0xFF

    return header_without_checksum + bytes([header_checksum]) + payload + bytes([payload_checksum])
```

Run

---

### 14.4 Testcase Generation Details

Suggested packets:

#### `001_short_input`

python

```python
packet = b"\xa5\x5a\x01"
```

Run

#### `002_bad_magic`

Create a valid HELLO packet, then corrupt `magic0`.

python

```python
packet = bytearray(make_packet(MSG_HELLO, 0, 1, b""))
packet[0] = 0x00
```

Run

Do not fix checksum.

Expected rejection is magic failure before checksum.

#### `003_bad_version`

Create valid HELLO packet, then corrupt version.

python

```python
packet = bytearray(make_packet(MSG_HELLO, 0, 1, b""))
packet[2] = 0x02
```

Run

Expected rejection is version failure before checksum.

#### `004_bad_checksum`

Create valid HELLO packet, then corrupt header checksum.

python

```python
packet = bytearray(make_packet(MSG_HELLO, 0, 1, b""))
packet[7] ^= 0xff
```

Run

Expected checksum failure.

#### `005_hello_ok`

python

```python
packet = make_packet(MSG_HELLO, 0x01, 0x10, b"\x7f")
```

Run

#### `006_auth_ok`

python

View all

```python
session_id = 0x22
payload = bytes([
    0x42,
    0x13,
    0x37,
    session_id ^ 0x5a,
])
packet = make_packet(MSG_AUTH, 0, session_id, payload)
```

Run

#### `007_write_config_without_auth`

python

```python
payload = bytes([0x02, 0xab])
packet = make_packet(MSG_WRITE_CONFIG, 0x00, 0x10, payload)
```

Run

#### `008_write_config_ok`

Use demo auth flag:

python

```python
payload = bytes([0x02, 0xab])
packet = make_packet(MSG_WRITE_CONFIG, 0x80, 0x10, payload)
```

Run

#### `009_write_config_oob`

Use demo auth flag and index 16:

python

```python
payload = bytes([0x10, 0xab])
packet = make_packet(MSG_WRITE_CONFIG, 0x80, 0x10, payload)
```

Run

---

## 15. Trace Analysis Design

`run.py analyze` should load JSONL events and compute:

- number of symbolic ranges;
- number of symbolic loads;
- number of symbolic stores;
- number of branches;
- list of handlers;
- list of bugs;
- final result code;
- whether expected handler matched;
- whether expected bug matched;
- whether expected return code matched.

It does not need to generate new inputs in version 1. If Z3 is installed, `analysis.py` may run a small satisfiability check for supported trace shapes, but solver-driven exploration is not required for the demo.

---

### 15.1 PASS/FAIL Rules

For each testcase, load:

text

```text
meta.json
```

Then check:

1. If `expect.handler` is not null, the trace must include a matching handler.
2. If `expect.handler` is null, the trace should include no handler.
3. If `expect.bug` is not null, the trace must include a matching bug.
4. If `expect.bug` is null, the trace should include no bug.
5. If `expect.ret` is not null, final result must equal it.

Print:

text

```text
Status: PASS
```

or:

text

```text
Status: FAIL
```

Also print specific mismatches.

---

### 15.2 Useful Trace Summary

Example output:

text

```text
Case: 009_write_config_oob
Description: WRITE_CONFIG packet with index 16 triggers OOB config write.

Trace summary:
  branches: 9
  loads: 20
  stores: 0
  symbolic ranges: 1
  handlers:
    - WRITE_CONFIG
  bugs:
    - OOB_CONFIG_WRITE
  result: -100

Status: PASS
Z3 not available: symbolic constraint check skipped
```

---

## 16. Error Codes

Use stable return codes so tests can assert them.

Suggested codes:

c

```c
#define RET_OK                    0
#define RET_ERR_SHORT            -1
#define RET_ERR_MAGIC0           -2
#define RET_ERR_VERSION          -3
#define RET_ERR_LENGTH           -4
#define RET_ERR_CHECKSUM         -5
#define RET_ERR_UNKNOWN_MSG      -6
#define RET_ERR_PAYLOAD          -7
#define RET_ERR_MAGIC1           -8
#define RET_ERR_AUTH            -20
#define RET_ERR_BUG_OOB        -100
```

Notes:

- `002_bad_magic` can return `RET_ERR_MAGIC0`.
- `003_bad_version` can return `RET_ERR_VERSION`.
- `004_bad_checksum` can return `RET_ERR_CHECKSUM`.
- `009_write_config_oob` can return `RET_ERR_BUG_OOB`.

---

## 17. Coding Guidelines

### 17.1 C Code

Use:

bash

```bash
gcc -Wall -Wextra -O0 -g
```

Keep code simple.

Avoid dependencies other than the C standard library.

Use fixed-size buffers:

c

```c
uint8_t buf[512];
```

Limit input size:

c

```c
#define MAX_INPUT 512
```

Recommended files:

text

```text
firmware/miniiot.c
src-demo/miniiot_instrumented.c
src-demo/sym_iot.c
src-demo/sym_iot.h
```

---

### 17.2 Python Code

Use only the Python standard library.

Recommended modules:

python

```python
argparse
json
os
pathlib
shutil
subprocess
sys
```

Run

No third-party dependencies are required. `z3` may be used opportunistically by `analysis.py` when installed, but the demo must still run without it.

---

### 17.3 JSONL Writing

Each event must be one line.

Do not pretty-print trace JSON.

Example:

text

```text
{"event":"branch","taken":true,"lhs":11,"rhs":9,"op":">="}
{"event":"result","ret":0}
```

---

## 18. README Requirements

`README.md` should include:

1. Project summary.
2. Directory layout.
3. Quick start.
4. Commands.
5. Example output.
6. Explanation that `bin-demo/` is reserved for future Qiling work.

Suggested quick start:

bash

```bash
python3 src-demo/run.py gen
python3 src-demo/run.py build
python3 src-demo/run.py run-all
python3 src-demo/run.py analyze 009_write_config_oob
```

Expected output should show that `009_write_config_oob` reports:

text

```text
OOB_CONFIG_WRITE
```

---

## 19. `bin-demo/README.md`

Create:

markdown

```markdown
# bin-demo

Reserved for the future binary-level firmware demo.

The current implementation is source-level and lives in `src-demo/`.

Future work may add:

- Qiling runner
- firmware ELF image
- memory map
- MMIO hooks
- UART model
- flash model
- binary-level traces
```

---

## 20. Future Extensions

Do not implement these in version 1, but keep the design compatible.

### 20.1 More Protocol Messages

Possible future messages:

c

```c
#define MSG_READ_CONFIG  0x04
#define MSG_PING         0x05
#define MSG_RESET        0x06
#define MSG_BULK_WRITE   0x07
```

---

### 20.2 More Testcases

Possible future testcases:

text

```text
010_unknown_msg_type
011_payload_len_too_large
012_auth_bad_user
013_auth_bad_token
014_write_config_index_15
015_write_config_index_17
016_hello_with_feature_flag
017_bulk_write_ok
018_bulk_write_oob
```

---

### 20.3 Constraint Solving

Version 1 focuses on CO3-style symbolic data collection and trace summaries.

Future versions may add:

- fuller path constraint extraction from `branch` events;
- simple mutation suggestions;
- required Z3 integration;
- automatic testcase generation.

Do not make solver-driven input generation required in the first version.

---

### 20.4 Binary-Level Qiling Demo

Future `bin-demo/` may emulate a compiled firmware image.

Potential layout:

text

```text
bin-demo/
├── README.md
├── run_qiling.py
├── hooks.py
├── memory_map.py
├── firmware-bin/
│   └── miniiot.elf
├── models/
│   ├── uart.py
│   └── flash.py
├── testcases/
└── traces/
```

The binary demo should ideally reuse the trace event concepts from `src-demo`, but it should not be required for version 1.

---

## 21. Implementation Order

Recommended implementation order:

1. Create directories.
2. Write `firmware/miniiot.c`.
3. Write `src-demo/sym_iot.h`.
4. Write `src-demo/sym_iot.c`.
5. Write `src-demo/miniiot_instrumented.c`.
6. Write `src-demo/build.sh`.
7. Write `src-demo/run.py`.
8. Generate testcases.
9. Build.
10. Run all testcases.
11. Analyze `009_write_config_oob`.
12. Write `README.md`.
13. Write `bin-demo/README.md`.

---

## 22. Acceptance Criteria

The first version is complete when the following commands work:

bash

```bash
python3 src-demo/run.py gen
python3 src-demo/run.py build
python3 src-demo/run.py run-all
python3 src-demo/run.py analyze 009_write_config_oob
```

And the analysis of `009_write_config_oob` shows:

text

```text
handler: WRITE_CONFIG
bug: OOB_CONFIG_WRITE
result: -100
Status: PASS
```

Also:

bash

```bash
python3 src-demo/run.py analyze 005_hello_ok
```

should show:

text

```text
handler: HELLO
bug: none
result: 0
Status: PASS
```

---

## 23. Core Design Principle

Keep version 1 small.

Do not split Python into many files yet.

Do not implement Qiling yet.

Do not add external dependencies.

The structure should remain:

text

```text
firmware/
    clean original firmware

src-demo/
    source-level instrumentation demo

bin-demo/
    reserved future binary-level demo
```
