# test/probes —— 手动探针脚本（pytest 不收集）

> 这些**不是 pytest 用例**，是 2026-11-15 做 v2.2 工业化评估时写的一次性验证脚本。
> 文件名 `probe_*.py` 不匹配 `pytest.ini` 的 `python_files = test_*.py`，所以不会被收集。
>
> **运行方式**（在仓库根目录）：
> ```bash
> PYTHONIOENCODING=utf-8 python test/probes/probe_tool_status_overwrite.py
> PYTHONIOENCODING=utf-8 python test/probes/probe_dangling_tool_calls.py
> PYTHONIOENCODING=utf-8 python test/probes/probe_minimax_dangling_400.py
> ```
>
> **下一步**：把它们改写成正式 pytest 用例（重点是第 2、3 个 —— 它们是
> `tool_calls` 悬空修复的「红灯」，改写前先确认能复现旧 bug）。
> 改写完成后，**整个 `probes/` 目录并入 `test/archive/`**（那里是过时脚本的归档区）。
> 设计与实施计划见 [`../../docs/status/测试体系.md`](../../docs/status/测试体系.md)
> 与 [`../../docs/plan/2026-11-16-test-suite-impl.md`](../../docs/plan/2026-11-16-test-suite-impl.md)。

| 脚本 | 验证什么 | 需要什么 |
|---|---|---|
| `probe_tool_status_overwrite.py` | 同一轮并发调用同一个工具两次（一次成功一次超时），状态字典会不会互相覆盖 | 只要 langgraph（假工具，不连 Milvus） |
| `probe_dangling_tool_calls.py` | 真实图跑一遍，每个 `tool_call` 是否都有对应的 `ToolMessage` | 需要 Milvus + MiniMax |
| `probe_minimax_dangling_400.py` | 直连 MiniMax API，构造「有 tool_calls 没 tool 应答」的消息序列，看是否报 400 | 需要 `.env` 里的 `MINIMAX_BASE_URL` / `MINIMAX_API_KEY` |

## 结论（2026-11-15 实测基线）

| 脚本 | 修复前 | 修复后（A1+A2+A3 落地） |
|---|---|---|
| `probe_tool_status_overwrite.py` | `{'rag_search': 'timeout'}` —— 1 个键，成功那条被冲掉 | 2 个键，按调用 id 各存各的 |
| `probe_dangling_tool_calls.py` | 悬空 2 / 总调用 7 | **悬空 0 / 总调用 5** |
| `probe_minimax_dangling_400.py` | HTTP 400 `invalid params, tool call and result not match (2013)` | 不变（这是 MiniMax 服务端的行为，改不了；只能保证我们不产生悬空消息） |

## 为什么第 3 个脚本仍然有价值

它证明的是**外部系统的约束**：只要消息序列里有「有 tool_calls 但没有 tool 应答」，
MiniMax 就会 400。我们改不了 MiniMax，但能保证自己不造出这种消息 ——
这正是 `iter_node.py` 提前一轮收手的原因。
