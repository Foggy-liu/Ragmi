"""agent/constants.py —— 从 configs/agent_config.yaml 加载 Agent 常量。

v2.2 新增：替代 v2.1 在 agent/state.py 内硬编码 MAX_ITERS / MAX_REFL。
超时预算（LLM_TIMEOUT / TOOL_TIMEOUT / TOTAL_TIMEOUT）也从这里加载，
改动超时不用改代码，只改 YAML。
"""
from pathlib import Path

import yaml

_CONFIG_PATH = Path(__file__).parent.parent / "configs" / "agent_config.yaml"

with open(_CONFIG_PATH, encoding="utf-8") as _f:
    _CONFIG = yaml.safe_load(_f)["agent"]

MAX_ITER: int = int(_CONFIG["iter"]["max_per_cycle"])
MAX_REFL: int = int(_CONFIG["reflect"]["max_absolute"])

# 超时预算（秒）
LLM_TIMEOUT: int = int(_CONFIG["timeout"]["llm"])
TOOL_TIMEOUT: int = int(_CONFIG["timeout"]["tool"])
TOTAL_TIMEOUT: int = int(_CONFIG["timeout"]["total"])

# 启动时校验：防止 YAML 误填 0 或负数
# MAX_ITER >= 2：iter 节点用 iter_count + 1 >= MAX_ITER 判断"这是最后一轮"。
# 若 MAX_ITER = 1，第一次进入 iter 就命中边界 → 永远不调 LLM → 永远不调工具，
# Agent 退化成"不带检索的纯闲聊"，所以下限是 2。
assert MAX_ITER >= 2, f"MAX_ITER must be >= 2, got {MAX_ITER}"
assert MAX_REFL >= 1, f"MAX_REFL must be >= 1, got {MAX_REFL}"
assert LLM_TIMEOUT >= 1, f"LLM_TIMEOUT must be >= 1, got {LLM_TIMEOUT}"
assert TOOL_TIMEOUT >= 1, f"TOOL_TIMEOUT must be >= 1, got {TOOL_TIMEOUT}"
assert TOTAL_TIMEOUT >= 1, f"TOTAL_TIMEOUT must be >= 1, got {TOTAL_TIMEOUT}"

# 总时限必须 >= 单次 LLM 超时，否则图一进门就已经过期了
assert TOTAL_TIMEOUT > LLM_TIMEOUT, (
    f"TOTAL_TIMEOUT ({TOTAL_TIMEOUT}) must be > LLM_TIMEOUT ({LLM_TIMEOUT})"
)
