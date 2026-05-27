/**
 * Extract structural facts from the AVDTP demo target.
 *
 * In production the target function list would come from an automated
 * candidate search (call-graph analysis + parameter-shape heuristics,
 * similar to the original RTCON paper's find_funcs stage).  For this
 * demo the list is hand-picked.
 *
 * This query does not report bugs.  It collects the raw facts that
 * the downstream analysis stage (make_analysis.py, future LLM) turns
 * into an analysis.json instrumentation plan.
 */

import cpp

predicate isTarget(Function f) {
  f.getName() = "avdtp_process_configuration" or
  f.getName() = "net_buf_pull_u8" or
  f.getName() = "net_buf_simple_pull_u8"
}

from string kind, Function f, int line, string text
where
  exists(Parameter p |
    isTarget(f) and
    p.getFunction() = f and
    kind = "param" and
    line = p.getLocation().getStartLine() and
    text = p.getName()
  )
  or
  exists(IfStmt s |
    isTarget(f) and
    s.getEnclosingFunction() = f and
    kind = "if" and
    line = s.getLocation().getStartLine() and
    text = s.getCondition().toString()
  )
  or
  exists(FunctionCall c |
    isTarget(f) and
    c.getEnclosingFunction() = f and
    kind = "call" and
    line = c.getLocation().getStartLine() and
    text = c.toString()
  )
  or
  exists(Expr e |
    isTarget(f) and
    e.getEnclosingFunction() = f and
    kind = "expr" and
    line = e.getLocation().getStartLine() and
    (
      e.toString().matches("%len%") or
      e.toString().matches("%data%")
    ) and
    text = e.toString()
  )
  or
  exists(ReturnStmt r |
    isTarget(f) and
    r.getEnclosingFunction() = f and
    kind = "return" and
    line = r.getLocation().getStartLine() and
    text = r.toString()
  )
select kind, f.getName(), line, text
