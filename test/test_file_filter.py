"""test/test_file_filter.py —— 文档入库去重（MD5 内容哈希）的行为测试（永远跑）。

只测 utils/docs/manager/filter.py + output.py 的纯逻辑和文件系统副作用，
不连 Milvus / Ollama / LLM。

覆盖两个真实出过问题的点：
1. **同一份文档再传一次不能重复入库**。旧实现多比了一次 mtime，而上传接口
   用 'wb' 覆盖写源文件 → 源文件 mtime 必然比产物新 → 每次都判成"需要处理"；
   output.py 又永不覆盖、只会造 _1/_2/... 副本 → txt/ 里堆出同内容副本，
   索引里全是重复 chunk。
2. **索引必须跨环境可用**。旧实现存绝对路径，宿主机（D:\\...）和容器
   （/app/...）各写各的，换个环境 Path(...).exists() 恒为 False → 去重失效。
   现在只存文件名，解析时用 output_dir 拼回来。
"""
import json
import os
import time
from pathlib import Path

import pytest

from utils.docs.manager.filter import FileFilter
from utils.docs.manager.output import OutputManager


@pytest.fixture()
def dirs(tmp_path):
    """(源目录, 输出目录) —— 模拟 documents/ 与 txt/。"""
    src = tmp_path / "documents"
    out = tmp_path / "txt"
    src.mkdir()
    out.mkdir()
    return src, out


def _write(path, content):
    path.write_text(content, encoding="utf-8")
    return path


def _touch_newer(path, seconds=10):
    """把文件的 mtime 推到未来，模拟"源文件被重新写了一遍"。"""
    future = time.time() + seconds
    os.utime(path, (future, future))


def test_f1_first_time_always_needs_processing(dirs):
    """没见过的内容 → 需要处理。"""
    src, out = dirs
    source = _write(src / "a.md", "内容甲")

    need, reason = FileFilter(out).should_process(source, ".md")

    assert need is True
    assert reason == "需要处理"


def test_f2_same_content_is_skipped(dirs):
    """同内容再传一次 → 跳过。"""
    src, out = dirs
    source = _write(src / "a.md", "内容甲")
    output = _write(out / "a_md.txt", "内容甲")
    filt = FileFilter(out)
    filt.record_processed(source, output)

    need, reason = filt.should_process(source, ".md")

    assert need is False
    assert reason == "内容相同，已处理过"


def test_f3_identical_content_under_another_filename_is_skipped(dirs):
    """不同文件名、内容相同 → 也跳过（这才是 MD5 去重的意义）。"""
    src, out = dirs
    first = _write(src / "a.md", "内容甲")
    output = _write(out / "a_md.txt", "内容甲")
    filt = FileFilter(out)
    filt.record_processed(first, output)

    second = _write(src / "b.md", "内容甲")

    need, _ = filt.should_process(second, ".md")

    assert need is False


def test_f4_reupload_with_newer_mtime_is_still_skipped(dirs):
    """重传（源文件 mtime 变新）仍然跳过 —— 旧实现就是死在这道 mtime 门上。"""
    src, out = dirs
    source = _write(src / "a.md", "内容甲")
    output = _write(out / "a_md.txt", "内容甲")
    filt = FileFilter(out)
    filt.record_processed(source, output)

    _touch_newer(source)
    assert source.stat().st_mtime > output.stat().st_mtime, "前提：源文件确实更新"

    need, reason = filt.should_process(source, ".md")

    assert need is False
    assert reason == "内容相同，已处理过"


def test_f5_changed_content_needs_processing(dirs):
    """内容变了 → 哈希变了 → 需要重新处理。"""
    src, out = dirs
    source = _write(src / "a.md", "内容甲")
    output = _write(out / "a_md.txt", "内容甲")
    filt = FileFilter(out)
    filt.record_processed(source, output)

    source.write_text("内容乙", encoding="utf-8")

    need, _ = filt.should_process(source, ".md")

    assert need is True


def test_f6_deleted_output_needs_processing(dirs):
    """产物文件被删了 → 需要重新处理（否则索引指向空处）。"""
    src, out = dirs
    source = _write(src / "a.md", "内容甲")
    output = _write(out / "a_md.txt", "内容甲")
    filt = FileFilter(out)
    filt.record_processed(source, output)
    output.unlink()

    need, _ = filt.should_process(source, ".md")

    assert need is True


def test_f7_index_stores_filename_not_absolute_path(dirs):
    """索引里只存文件名 → 宿主机/容器共用同一份索引。"""
    src, out = dirs
    source = _write(src / "a.md", "内容甲")
    output = _write(out / "a_md.txt", "内容甲")
    filt = FileFilter(out)
    filt.record_processed(source, output)

    stored = json.loads((out / ".file_filter.json").read_text(encoding="utf-8"))
    values = [v["output_path"] for v in stored.values()]

    assert values == ["a_md.txt"]


def test_f8_legacy_absolute_path_index_still_resolves(dirs):
    """旧索引（存绝对路径）加载后要能解析到当前环境的文件。"""
    src, out = dirs
    source = _write(src / "a.md", "内容甲")
    output = _write(out / "a_md.txt", "内容甲")
    legacy_path = str(output).replace("\\", "/")
    (out / ".file_filter.json").write_text(
        json.dumps(
            {
                "deadbeef": {
                    "output_path": legacy_path,
                    "source_file": str(source),
                    "recorded_time": time.time(),
                }
            }
        ),
        encoding="utf-8",
    )
    # 把索引里的哈希换成源文件真实的哈希
    filt = FileFilter(out)
    real_hash = filt._get_hash(source)
    filt.file_index = {
        real_hash: {"output_path": legacy_path, "source_file": str(source)}
    }
    filt._save_index()

    reloaded = FileFilter(out)

    need, _ = reloaded.should_process(source, ".md")
    assert need is False, "旧格式的绝对路径应被迁移成文件名并正确解析"


def test_f9_reupload_does_not_create_numbered_copy(dirs):
    """回归网：同一份文档传两次，txt/ 里只能有一个产物，不该冒出 a_md_1.txt。"""
    src, out = dirs
    source = _write(src / "a.md", "内容甲")
    manager = OutputManager(out)
    filt = FileFilter(out)

    # 第一次上传
    need, _ = filt.should_process(source, ".md")
    assert need is True
    first = manager.get_output_path(source, "md")
    first.write_text("内容甲", encoding="utf-8")
    filt.record_processed(source, first)

    # 第二次上传同一个文件（源文件被重写，mtime 变新）
    source.write_text("内容甲", encoding="utf-8")
    _touch_newer(source)
    need, _ = filt.should_process(source, ".md")
    assert need is False, "第二次上传应被去重拦下"

    produced = sorted(p.name for p in out.glob("*.txt"))
    assert produced == ["a_md.txt"], f"不该出现编号副本，实际产物：{produced}"
