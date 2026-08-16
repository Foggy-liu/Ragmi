"""agent/constants.py —— 从 configs/agent_config.yaml 加载 Agent 节点上限常量。

v2.2 新增：替代 v2.1 在 agent/state.py 内硬编码 MAX_ITERS / MAX_REFL。
"""
from pathlib import Path

import yaml

_CONFIG_PATH = Path(__file__).parent.parent / "configs" / "agent_config.yaml"

with open(_CONFIG_PATH, encoding="utf-8") as _f:
    _CONFIG = yaml.safe_load(_f)["agent"]

MAX_ITER: int = int(_CONFIG["iter"]["max_per_cycle"])
MAX_SYNTH: int = int(_CONFIG["synth"]["max_per_cycle"])
MAX_REFL: int = int(_CONFIG["reflect"]["max_absolute"])

# 启动时校验：防止 YAML 误填 0 或负数
assert MAX_ITER >= 1, f"MAX_ITER must be >= 1, got {MAX_ITER}"
assert MAX_SYNTH >= 1, f"MAX_SYNTH must be >= 1, got {MAX_SYNTH}"
assert MAX_REFL >= 1, f"MAX_REFL must be >= 1, got {MAX_REFL}"
