"""test/test_vector_split.py —— vector_split 端到端测试。

验证：
1. vector_split() 跑通（不再卡在 embed 阶段）
2. txt_data alias 被创建
3. 集合有行数 > 0

前置：Milvus 容器健康、Ollama 在 11434 提供 bge-large embedding。
直接 python test/test_vector_split.py 跑。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pymilvus import MilvusClient
from utils.txt_spliter.vector_main import vector_split


def test_alias_is_created_with_timestamped_collection():
    """alias 应指向时间戳命名的新集合，集合行数 > 0。"""
    # 记录运行前的 alias 状态
    client = MilvusClient(host="127.0.0.1", port="19530")
    try:
        before = client.describe_alias("txt_data")
        before_coll = before["collection_name"]
    except Exception:
        before_coll = None

    # 跑 vector_split
    vector_split()

    # 验证 alias 存在
    info = client.describe_alias("txt_data")
    coll = info["collection_name"]
    assert coll.startswith("txt_data_"), f"alias 应指向 txt_data_<ts> 格式，实际: {coll}"

    # 验证是新集合（不是切换回旧的）
    if before_coll:
        assert coll != before_coll, f"alias 应切换到新集合，但仍是 {coll}"

    # 验证行数 > 0（用 query 不用 stats：get_collection_stats 写入后是缓存值，会返回 0）
    rows = client.query(coll, output_fields=["id"], limit=10)
    assert len(rows) > 0, f"期望 query 返回行，实际 {len(rows)}"
    print(f"[PASS] alias 指向 {coll}, query 返回 {len(rows)} 行")


if __name__ == "__main__":
    test_alias_is_created_with_timestamped_collection()
    print("\nAll tests passed.")
