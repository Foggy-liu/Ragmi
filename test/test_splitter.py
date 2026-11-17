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


@pytest.mark.xfail(
    strict=True,
    reason="P1-7: max_chars 没传给 LangChain 切分器 —— 代码写死 chunk_size=300，"
           "configs/model_config.yaml 写的是 280（漂移未修）",
)
def test_s5_max_chars_is_honored():
    """（期望行为）Splitter(max_chars=100) 时每块都应 ≤ 100 字符。"""
    chunks = Splitter(max_chars=100).split(SAMPLE)

    assert all(len(chunk) <= 100 for chunk in chunks)
