import common

# device.py - 固件端：协议栈 + CO3 插桩 + 自动输出执行轨迹
# 无任何求解逻辑，纯设备具体执行。
CO3_TRACE = common.CO3_TRACE
MEM_R = common.MEM_R
BRANCH = common.BRANCH
CALL = common.CALL
RET = common.RET
BUG = common.BUG
BRANCH_ADDR = common.BRANCH_ADDR
BRANCH_LEN = common.BRANCH_LEN
FUNC_CHECK_ADDR = common.FUNC_CHECK_ADDR
FUNC_CHECK_LENGTH = common.FUNC_CHECK_LENGTH

trace = []
sym_mem = [0] * 8


def co3_stub(stub_type, tag, value):
    trace.append(f"{stub_type} {tag} {int(value)}")


def save_trace():
    CO3_TRACE.write_text("\n".join(trace) + "\n", encoding="utf-8")


def clear_trace():
    trace.clear()


def sym_read(offset):
    value = sym_mem[offset]
    co3_stub(MEM_R, offset, value)
    return value


def check_addr(addr, input_offset):
    co3_stub(CALL, FUNC_CHECK_ADDR, input_offset)
    result = addr == 0x5A
    co3_stub(RET, FUNC_CHECK_ADDR, result)
    return result


def check_length(length, input_offset):
    co3_stub(CALL, FUNC_CHECK_LENGTH, input_offset)
    result = 0 < length <= 4
    co3_stub(RET, FUNC_CHECK_LENGTH, result)
    return result


def run_device():
    clear_trace()
    print("[device] run firmware")

    addr = sym_read(0)
    length = sym_read(1)

    addr_ok = check_addr(addr, 0)
    co3_stub(BRANCH, BRANCH_ADDR, addr_ok)
    if not addr_ok:
        print("[device] reject: bad addr")
        save_trace()
        return False

    len_ok = check_length(length, 1)
    co3_stub(BRANCH, BRANCH_LEN, len_ok)
    if not len_ok:
        print("[device] reject: bad len")
        save_trace()
        return False

    co3_stub(BUG, 0, 1)
    print("[device] BUG path reached")
    save_trace()
    return True


def set_input(idx, val):
    sym_mem[idx] = val & 0xFF


if __name__ == "__main__":
    set_input(0, 0x10)
    set_input(1, 0x09)
    run_device()
    print(f"trace saved to {CO3_TRACE}")
