"""
复现 / 验证 langchain_ollama 与直连 Ollama HTTP 在代理环境下的差异。

跑 4 个测试：
  T1 直连 HTTP /api/embeddings       单条
  T2 直连 HTTP /api/embed            批量
  T3 langchain_ollama.embed_query    单条
  T4 langchain_ollama.embed_documents 批量

三种预期：
  - 当前无代理干扰：4 个全过 → 走 evil_proxy 强制复现
  - T4 挂 / T3 过：bug 真实存在
  - T3 T4 全挂：普遍连接问题（Ollama 没起或代理设错），跟 bug 无关

用法：
  # 步骤1：当前环境基线
  python test/repro_embed_clients.py

  # 步骤2：强制走代理（哪怕本机没设，也会触发连接错误）
  HTTP_PROXY=http://127.0.0.1:7890 python test/repro_embed_clients.py

  # 步骤3：配合 evil_proxy.py 看精确复现
  #   终端1:  python test/evil_proxy.py
  #   终端2:  HTTP_PROXY=http://127.0.0.1:7890 python test/repro_embed_clients.py
"""

import os
import sys


def section(title):
    print(f"\n{'=' * 70}\n  {title}\n{'=' * 70}")


def env_summary():
    section("环境变量")
    print(f"  HTTP_PROXY  = {os.environ.get('HTTP_PROXY')!r}")
    print(f"  HTTPS_PROXY = {os.environ.get('HTTPS_PROXY')!r}")
    print(f"  NO_PROXY    = "
          f"{os.environ.get('NO_PROXY') or os.environ.get('no_proxy')!r}")

    section("Ollama 探活")
    try:
        import requests
        r = requests.get("http://127.0.0.1:11434/api/tags", timeout=3)
        if r.status_code != 200:
            print(f"  ❌ Ollama 状态码: {r.status_code}")
            return False
        models = [m["name"] for m in r.json().get("models", [])]
        print(f"  已装模型: {models}")
        has_bge = any("bge-large" in m for m in models)
        if not has_bge:
            print("  ❌ bge-large 不在模型列表里，请先：ollama pull bge-large")
            return False
        return True
    except Exception as e:
        print(f"  ❌ Ollama 不通: {type(e).__name__}: {e}")
        print("  请先启动 Ollama 服务")
        return False


def run_test(name, fn):
    print(f"\n--- {name} ---")
    try:
        ok, info = fn()
        print(f"  ✅ {info}" if ok else f"  ❌ {info}")
        return ok
    except Exception as e:
        print(f"  ❌ 异常: {type(e).__name__}: {e}")
        return False


# ============= 测试函数 =============


def t1_direct_single():
    """直连 Ollama /api/embeddings（单文本端点）"""
    import requests
    r = requests.post(
        "http://127.0.0.1:11434/api/embeddings",
        json={"model": "bge-large", "prompt": "hello world"},
        timeout=10,
    )
    r.raise_for_status()
    vec = r.json()["embedding"]
    return True, f"dim={len(vec)}, endpoint=/api/embeddings"


def t2_direct_batch():
    """直连 Ollama /api/embed（批量端点）"""
    import requests
    texts = [f"text_{i}" for i in range(10)]
    r = requests.post(
        "http://127.0.0.1:11434/api/embed",
        json={"model": "bge-large", "input": texts},
        timeout=60,
    )
    r.raise_for_status()
    vecs = r.json()["embeddings"]
    return True, f"{len(vecs)} 个向量, endpoint=/api/embed"


def t3_lc_query():
    """langchain_ollama.embed_query（单条）"""
    from langchain_ollama import OllamaEmbeddings
    embed = OllamaEmbeddings(
        model="bge-large", base_url="http://127.0.0.1:11434"
    )
    vec = embed.embed_query("hello world")
    return True, f"dim={len(vec)}"


def t4_lc_documents():
    """langchain_ollama.embed_documents（批量）"""
    from langchain_ollama import OllamaEmbeddings
    embed = OllamaEmbeddings(
        model="bge-large", base_url="http://127.0.0.1:11434"
    )
    texts = [f"text_{i}" for i in range(10)]
    vecs = embed.embed_documents(texts)
    return True, f"{len(vecs)} 个向量"


# ============= 主流程 =============


def main():
    if not env_summary():
        sys.exit(1)

    results = {}
    results["T1 直连单条"]      = run_test("T1: 直连 HTTP /api/embeddings",       t1_direct_single)
    results["T2 直连批量"]      = run_test("T2: 直连 HTTP /api/embed",            t2_direct_batch)
    results["T3 langchain 单条"] = run_test("T3: langchain_ollama.embed_query",    t3_lc_query)
    results["T4 langchain 批量"] = run_test("T4: langchain_ollama.embed_documents", t4_lc_documents)

    section("结果分析")

    all_ok = all(results.values())
    t1, t2, t3, t4 = (
        results["T1 直连单条"],
        results["T2 直连批量"],
        results["T3 langchain 单条"],
        results["T4 langchain 批量"],
    )

    if all_ok:
        print("  当前 4 测试全过 → 当前环境无代理干扰")
        print()
        print("  下一步走 evil_proxy 强制复现 bug：")
        print("    终端1: python test/evil_proxy.py")
        print("    终端2: HTTP_PROXY=http://127.0.0.1:7890 \\")
        print("            python test/repro_embed_clients.py")

    elif (not t4) and t3 and t1 and t2:
        # 关键模式：直连和 langchain 单条全过，只有 langchain 批量挂
        print("  🚨 关键模式复现：批量挂（T4）、单条过（T3）、直连全过（T1/T2）")
        print("  → 这就是你简历上描述的那个 bug。")
        print("  → 现在你可以放心地讲：你亲眼看到 langchain_ollama")
        print("    批量调用挂掉、直连 requests 没事。")

    elif (not t4) and (not t3):
        print("  ⚠️  T3 和 T4 都挂了 → 普遍连接问题，不是 bug 本质。")
        print("  排查方向：")
        print("    - Connection refused → Ollama 没起")
        print("    - ProxyError → 代理端口设错或代理软件没开")
        print("    - 如果想看精确复现，还是走 evil_proxy 模式")

    elif t4 and (not t3):
        print("  ⚠️  T3 挂 T4 过 —— 跟代码注释反着。可能是单条端点临时抽风，重跑一次。")

    else:
        print("  其他组合，看具体哪条挂哪条过。")
        print(f"  详情: {results}")

    section("下一步")
    print("  跑完把结果（哪几条 ✅ 哪几条 ❌ + 异常类型）告诉我，")
    print("  我根据结果给出最终方案：背话术 / 改代码 / 修简历。")


if __name__ == "__main__":
    main()
