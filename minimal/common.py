from pathlib import Path

# common.py - CO3 插桩约定 + 编译期从固件提取出的极简 SVFG 信息。
# 设备端使用插桩 ID；主机端使用 EXTRACTED_SVFG 还原分支约束。

CO3_TRACE = Path(__file__).resolve().with_name("co3_trace.txt")
CO3_LOG = Path(__file__).resolve().with_name("co3_log.txt")

# === CO3 插桩类型 ===
MEM_R = 1    # 符号内存读
BRANCH = 3  # 分支条件，pass-to-solver
CALL = 4    # 函数调用
RET = 5     # 函数返回
BUG = 9     # demo 目标路径

# 分支唯一 ID，由插桩/编译期分析分配。
BRANCH_ADDR = 1
BRANCH_LEN = 2

# 函数唯一 ID，由插桩/编译期分析分配。
FUNC_CHECK_ADDR = 1
FUNC_CHECK_LENGTH = 2

# 分支使用哪个函数返回值作为条件。
BRANCH_TO_FUNC = {
    BRANCH_ADDR: FUNC_CHECK_ADDR,
    BRANCH_LEN: FUNC_CHECK_LENGTH,
}

# 模拟 CO3 编译期提取出的函数级 SVFG。
# 真实 CO3 里这部分来自 LLVM/编译器分析；demo 里用数据表表示。
# param0 的实际来源，要等运行时 CALL 事件告诉主机。
EXTRACTED_SVFG = {
    FUNC_CHECK_ADDR: ("eq_const", "param0", 0x5A),      # param0 == 0x5A
    FUNC_CHECK_LENGTH: ("range_u8", "param0", 1, 4),    # 1 <= param0 <= 4
}

def stub_name(stub_type):
    names = {
        MEM_R: "MEM_R",
        CALL: "CALL",
        RET: "RET",
        BRANCH: "BRANCH",
        BUG: "BUG",
    }
    return names.get(stub_type, f"UNKNOWN({stub_type})")


def branch_name(branch_id):
    names = {
        BRANCH_ADDR: "BRANCH_ADDR",
        BRANCH_LEN: "BRANCH_LEN",
    }
    return names.get(branch_id, f"branch_{branch_id}")


def call_name(call_id):
    names = {
        FUNC_CHECK_ADDR: "check_addr",
        FUNC_CHECK_LENGTH: "check_length",
    }
    return names.get(call_id, f"call_{call_id}")


def bool_text(value):
    return "true" if value else "false"


# ----------------------
# 方便调试
# ----------------------
def reset_log():
    CO3_LOG.write_text("", encoding="utf-8")

def log(message=""):
    with CO3_LOG.open("a", encoding="utf-8") as f:
        f.write(f"{message}\n")


def explain_event(event):
    stub_type, tag, value = event

    if stub_type == MEM_R:
        return f"MEM_R    input[{tag}] = 0x{value:02x} ({value})"

    if stub_type == CALL:
        return f"CALL     {call_name(tag)}(param0 <- input[{value}])"

    if stub_type == RET:
        return f"RET      {call_name(tag)} -> {bool_text(value)}"

    if stub_type == BRANCH:
        return f"BRANCH   {branch_name(tag)} -> {bool_text(value)}"

    if stub_type == BUG:
        return "BUG      target path reached"

    return f"{stub_name(stub_type)} tag={tag} value={value}"

