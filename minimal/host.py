# host.py - 主机端：解析 trace + 绑定 SVFG 模板 + 符号求解
# 注意：CO3 不是从 trace 里“猜出协议语义”。
# trace 提供运行时事实；EXTRACTED_SVFG 表示编译期从固件提取的信息。
from z3 import And, BitVec, Solver, UGE, ULE, sat

import common
import device

# ======================
# 【核心0】读取“从固件提取出的”极简 SVFG 信息
#  Symbolic Value Flow Graph
# ======================
def build_formula_from_extracted_svfg(branch_id, sym_vars, call_args):
    func_id = common.BRANCH_TO_FUNC[branch_id]
    input_idx = call_args[func_id]
    svfg = common.EXTRACTED_SVFG[func_id]
    op = svfg[0]

    if op == "eq_const":
        _, _param, const = svfg
        return sym_vars[input_idx] == const

    if op == "range_u8":
        _, _param, lo, hi = svfg
        return And(UGE(sym_vars[input_idx], lo), ULE(sym_vars[input_idx], hi))

    raise KeyError(op)


# ======================
# 【核心1】读取设备原始执行轨迹
# ======================
def read_trace():
    events = []
    with device.CO3_TRACE.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                stub_type, tag, value = line.split()
                events.append((int(stub_type), int(tag), int(value)))
    print(f"[host] trace records: {len(events)}")
    common.log("decoded trace:")
    for event in events:
        common.log(f"  {common.explain_event(event)}    raw={event}")
    return events


# ======================
# 【核心2】动态分析 trace：提取符号变量 + 分支路径
# ======================
def analyze_trace(events):
    sym_vars = {}
    concrete_inputs = {}
    call_args = {}
    returns = {}
    branches = []

    for stub_type, tag, value in events:
        if stub_type == device.MEM_R:
            sym_vars[tag] = BitVec(f"input_{tag}", 8)
            concrete_inputs[tag] = value
        elif stub_type == device.CALL:
            call_args[tag] = value
        elif stub_type == device.RET:
            returns[tag] = bool(value)
        elif stub_type == device.BRANCH:
            branches.append((tag, bool(value)))

    print(f"[host] symbolic inputs: {list(sym_vars.keys())}")
    print(f"[host] call args: {call_args}")
    print(f"[host] branches: {branches}")
    common.log("symbolic inputs:")
    for idx in sorted(sym_vars):
        common.log(f"  input_{idx}: concrete=0x{concrete_inputs[idx]:02x}, z3={sym_vars[idx]}")
    common.log("call bindings:")
    for func_id, input_idx in call_args.items():
        ret = returns.get(func_id)
        ret_text = common.bool_text(ret) if ret is not None else "unknown"
        common.log(f"  {common.call_name(func_id)}.param0 <- input_{input_idx}, return={ret_text}")
    common.log("branches:")
    for branch_id, taken in branches:
        common.log(f"  {common.branch_name(branch_id)}: {common.bool_text(taken)}")
    return sym_vars, call_args, branches


# ======================
# 【核心3】构造约束：保留已通过分支，翻转第一个失败分支
# ======================
def flip_first_failed_branch(sym_vars, call_args, branches):
    solver = Solver()
    common.log("constraints added to Z3:")

    for branch_id, taken in branches:
        make_branch_true = build_formula_from_extracted_svfg(branch_id, sym_vars, call_args)

        if taken:
            solver.add(make_branch_true)
            print(f"[host] keep {common.branch_name(branch_id)}=true")
            common.log(f"  keep {common.branch_name(branch_id)}=true: {make_branch_true}")
        else:
            # 翻转就在这里：
            # 设备本轮告诉我们 branch_id 是 false；
            # 主机下一轮强制同一个分支条件为 true。
            solver.add(make_branch_true)
            print(f"[host] flip {common.branch_name(branch_id)}: false -> true")
            common.log(f"  flip {common.branch_name(branch_id)}: false -> true: {make_branch_true}")
            break

    common.log("solver.sexpr():")
    common.log(solver.sexpr())
    return solver


# ======================
# 【核心4】求解下一轮输入：这里只读 Z3 的答案，不负责翻转
# ======================
def solve_next_input(solver, sym_vars, current_input):
    result = solver.check()
    common.log(f"solver.check(): {result}")
    if result != sat:
        print("[host] unsat")
        return None

    model = solver.model()
    common.log("model:")
    for item in model.decls():
        common.log(f"  {item.name()} = {model[item]}")

    next_input = dict(current_input)

    for idx, var in sym_vars.items():
        value = model[var]
        if value is not None:
            next_input[idx] = value.as_long()

    print(f"[host] next input: {fmt(next_input)}")
    common.log(f"current input: {fmt(current_input)}")
    common.log(f"next input:    {fmt(next_input)}")
    return next_input


def run_once(values):
    for idx, val in values.items():
        device.set_input(idx, val)
    return device.run_device()


def fmt(values):
    return "{" + ", ".join(f"{i}: 0x{v:02x}" for i, v in sorted(values.items())) + "}"


# ======================
# 完整 CO3 极简闭环
# ======================
if __name__ == "__main__":
    current_input = {0: 0x10, 1: 0x09}
    common.reset_log()

    RUN_ROUNDS = 3
    for round_id in range(1, RUN_ROUNDS + 1):
        print(f"\nround {round_id}, input = {fmt(current_input)}")
        common.log("=" * 50)
        common.log(f"round {round_id}")
        common.log(f"device input: {fmt(current_input)}")

        if run_once(current_input):
            print("[host] done")
            common.log("device reached BUG path")
            break

        trace = read_trace()
        sym_vars, call_args, branches = analyze_trace(trace)
        solver = flip_first_failed_branch(sym_vars, call_args, branches)
        current_input = solve_next_input(solver, sym_vars, current_input)

        if current_input is None:
            break

    print(f"[host] z3 log saved to {common.CO3_LOG}")
