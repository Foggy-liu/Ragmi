"""test/test_splitter.py —— 摄取切分的纯函数测试（永远跑）。

不 embed、不连 Milvus、不碰向量库 —— 只测 utils/txt_spliter/spliter.py 的切分逻辑。
补的是 test_vector_split.py 标 slow 之后无人跑的那个洞。

⚠️ 切分器用 chunk_overlap=30 → 相邻块**故意**有 30 个字符的重叠。
所以"拼接结果 == 原文"这种断言是错的（实测会多出重叠部分）。
正确的不变式是：每块都是原文的子串 + 首块以原文开头 + 末块以原文结尾。
"""
import pytest

from utils.txt_spliter.spliter import Splitter

SAMPLE = "这是一段用来测试切分逻辑的中文文本。" * 40 + "结尾标记END"


def test_s1_empty_text_returns_no_chunks():
    """空文本 → 没有块。"""
    assert Splitter().split("") == []


def test_s2_short_text_returns_single_chunk():
    """短文本 → 单块，且原样返回。"""
    chunks = Splitter().split("很短的一段话")

    assert len(chunks) == 1
    assert chunks[0] == "很短的一段话"


def test_s3_chunks_are_non_empty_and_within_limit():
    """每块非空、长度 ≤ 300（LangChain 切分器的 chunk_size）。"""
    chunks = Splitter().split(SAMPLE)

    assert chunks
    assert all(chunk.strip() for chunk in chunks)
    assert all(len(chunk) <= 300 for chunk in chunks)


def test_s4_no_content_loss():
    """无内容丢失：每块都是原文子串，首块以原文开头，末块以原文结尾。"""
    chunks = Splitter().split(SAMPLE)

    assert all(chunk in SAMPLE for chunk in chunks)
    assert chunks[0].startswith(SAMPLE[:30])
    assert chunks[-1].endswith(SAMPLE[-30:])


def test_s5_max_chars_is_honored():
    """Splitter(max_chars=100) 时每块都应 ≤ 100 字符。

    修复前 max_chars 没传给 LangChain 切分器（写死 chunk_size=300）→ 这条 xfail（P1-7）。
    """
    chunks = Splitter(max_chars=100).split(SAMPLE)

    assert all(len(chunk) <= 100 for chunk in chunks)


def test_s6_default_comes_from_yaml():
    """默认切分参数来自 configs/model_config.yaml，不再是代码写死的值。

    固定住"配置只有一个事实来源"这条（P1-7 的另一半：YAML 从没被读过）。
    """
    import yaml
    from pathlib import Path

    config_path = Path(__file__).resolve().parents[1] / "configs" / "model_config.yaml"
    with open(config_path, encoding="utf-8") as f:
        expected = yaml.safe_load(f)["EMBEDDING_CONFIG"]["text_splitter"]

    splitter = Splitter()

    assert splitter.max_chars == expected["chunk_size"]
    assert splitter.overlap == expected["chunk_overlap"]
    assert splitter.langchain_splitter._chunk_size == expected["chunk_size"]
    assert splitter.langchain_splitter._chunk_overlap == expected["chunk_overlap"]
