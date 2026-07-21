"""utils/logging.py —— 统一日志配置。

格式：时间 级别 模块 消息
例：2026-07-19 14:23:01 INFO agent.runtime ask() entry query="..."

调用方式：
- main.py lifespan 启动时调 setup_logging("INFO") 一次
- 各模块用 get_logger(__name__) 拿 logger，调用 logger.info / .warning / .exception
"""
import logging
import sys


def setup_logging(level: str = "INFO"):
    """初始化项目级 logger。

    Why force=True：basicConfig 默认幂等，但有时被 pytest / 第三方库先调过；
    force=True 强制覆盖，确保我们的格式生效。
    Why 静默 httpx/httpcore：调 LLM API 时这两个库默认 DEBUG 会刷屏，每条 HTTP 请求
    3-5 行噪声，业务日志被淹没。
    """
    fmt = "%(asctime)s %(levelname)s %(name)s %(message)s"
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format=fmt,
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
        force=True,  # 覆盖已有的 root logger 配置
    )
    # 静默 httpx / httpcore 的 DEBUG 日志
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """便捷获取 logger。name 通常传 __name__（模块路径）。"""
    return logging.getLogger(name)