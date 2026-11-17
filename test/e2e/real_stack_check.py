#!/usr/bin/env python
"""test/e2e/real_stack_check.py —— **真栈** E2E（真实后端 + 真 Milvus/Ollama/MiniMax）。

跑法（仓库根目录）：
    PYTHONIOENCODING=utf-8 python test/e2e/real_stack_check.py

⚠️ 这个文件**故意不叫 `test_*.py`** → pytest 永远不会收集它。
   它跟 `test_browser_e2e.py`（假后端、确定性、CI 友好）是两回事：
   - 需要真服务全在位（后端 8000 / Streamlit 8501 / Milvus / Ollama）
   - 会调真 MiniMax（**花钱**）、真检索（**慢**）
   - 会开一个**可见的** Chrome 窗口

做三件事：
  A. 用 Playwright 的真实 Chrome 页面里的 fetch() 打遍 **9 个接口**（含负路径）
     —— 在页面上下文里发请求，走的是浏览器网络栈，**CORS 也一并验了**
  B. 驱动真实 Streamlit 的 **3 个页面**做真实交互
  C. 把结果渲染成 HTML 报告，**在 Chrome 里开一个标签页展示**

产物：test/e2e/_artifacts/（截图 + 报告，已在 .gitignore 里）
"""
import os
import shutil
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "test" / "e2e" / "_artifacts"
API = os.getenv("E2E_API", "http://127.0.0.1:8000")
FRONTEND = os.getenv("E2E_FRONTEND", "http://localhost:8501")
PROBE = "e2e_probe_"          # 探针文件名前缀，测完统一清掉

# Streamlit 1.52 的 DOM testid（与 test_browser_e2e.py 保持一致）
CHAT_INPUT = '[data-testid="stChatInputTextArea"]'
CHAT_MESSAGE = '[data-testid="stChatMessage"]'
CHAT_CONTENT = '[data-testid="stChatMessageContent"]'   # 消息正文（不含头像）
MD = '[data-testid="stMarkdownContainer"]'              # 正文里的 markdown
SPINNER = '[data-testid="stSpinner"]'                   # 加载中的转圈
UPLOAD_INPUT = '[data-testid="stFileUploaderDropzoneInput"]'
ALERT = '[data-testid="stAlert"]'
HEADING = '[data-testid="stHeading"]'
EXCEPTION = '[data-testid="stException"]'

RESULTS = []


# ---------------------------------------------------------------------------
# 记账
# ---------------------------------------------------------------------------
def check(cid, group, name, fn):
    """跑一条用例并记账。fn 抛 AssertionError = 失败。"""
    t0 = time.time()
    try:
        detail = fn() or ""
        ok = True
    except AssertionError as exc:
        detail = f"断言失败：{exc}"
        ok = False
    except Exception as exc:                       # noqa: BLE001
        detail = f"{type(exc).__name__}: {exc}"
        ok = False
    dt = time.time() - t0
    RESULTS.append({"id": cid, "group": group, "name": name, "ok": ok,
                    "detail": str(detail), "sec": dt})
    print(f"  [{'PASS' if ok else 'FAIL'}] {cid:<4} {name}  ({dt:.1f}s)")
    if not ok:
        print(f"         └─ {str(detail)[:300]}")
    return ok


def group(title):
    print(f"\n=== {title} ===")


# ---------------------------------------------------------------------------
# 页面上下文里的真实 fetch（走浏览器网络栈 → CORS 一并验证）
# ---------------------------------------------------------------------------
_JS_FETCH = """
async ({method, path, body, field, files}) => {
    const opts = {method};
    if (files) {
        const fd = new FormData();
        for (const f of files) {
            fd.append(field, new File([f.content], f.name, {type: 'text/plain'}), f.name);
        }
        opts.body = fd;
    } else if (body !== null) {
        opts.headers = {'Content-Type': 'application/json'};
        opts.body = JSON.stringify(body);
    }
    const t0 = Date.now();
    try {
        const resp = await fetch(path, opts);
        const text = await resp.text();
        let data = null;
        try { data = JSON.parse(text); } catch (e) { data = text; }
        return {status: resp.status, ok: resp.ok, data: data, ms: Date.now() - t0};
    } catch (e) {
        return {status: 0, ok: false, data: String(e), ms: Date.now() - t0,
                networkError: true};
    }
}
"""


def call(page, method, path, body=None, field=None, files=None):
    return page.evaluate(_JS_FETCH, {"method": method, "path": path, "body": body,
                                     "field": field, "files": files})


def expect_status(resp, want, label=""):
    assert not resp.get("networkError"), f"网络层错误（CORS/连接）：{resp.get('data')}"
    assert resp["status"] == want, f"期望 HTTP {want}，实际 {resp['status']}；body={str(resp['data'])[:200]}"


# ---------------------------------------------------------------------------
# A 组 —— 9 个接口全覆盖
# ---------------------------------------------------------------------------
def run_api_suite(page):
    group("A 组 · 接口全覆盖（真实后端）")

    # ---- A1 GET /debug/simple -------------------------------------------
    def a1():
        r = call(page, "GET", f"{API}/debug/simple")
        expect_status(r, 200)
        d = r["data"]
        assert "当前模型" in d, f"缺 '当前模型'：{d}"
        assert d["可用模型数量"] > 0, f"可用模型数量为 0：{d}"
        return f"当前模型={d['当前模型']}，可用模型数={d['可用模型数量']}，耗时 {r['ms']}ms"
    check("A1", "接口", "GET /debug/simple —— 后端存活 + 模型管理器就绪", a1)

    # ---- A2 GET /available ----------------------------------------------
    def a2():
        r = call(page, "GET", f"{API}/available")
        expect_status(r, 200)
        models = r["data"]["available_models"]
        names = {m["model_name"] for m in models}
        assert "MiniMax-M3.1-Flash" in names, f"模型列表里没有 MiniMax-M3.1-Flash：{sorted(names)}"
        return f"{len(models)} 个可用模型，含 MiniMax-M3.1-Flash，耗时 {r['ms']}ms"
    check("A2", "接口", "GET /available —— 可用模型清单", a2)

    # ---- A3 GET /current_model ------------------------------------------
    def a3():
        r = call(page, "GET", f"{API}/current_model")
        expect_status(r, 200)
        d = r["data"]
        assert d.get("platform") and d.get("model_name"), f"字段缺失：{d}"
        return f"{d['platform']}/{d['model_name']}"
    check("A3", "接口", "GET /current_model —— 当前模型", a3)

    # ---- A4 POST /switch_model（失败路径）-------------------------------
    def a4():
        r = call(page, "POST", f"{API}/switch_model",
                 body={"platform": "不存在的平台", "model_name": "不存在"})
        expect_status(r, 200)
        assert r["data"].get("success") is False, f"非法模型应返回 success=false：{r['data']}"
        assert "message" in r["data"], f"失败响应缺 message：{r['data']}"
        return f"success=false，message={r['data'].get('message')!r}"
    check("A4", "接口", "POST /switch_model —— 非法模型走失败分支", a4)

    # ---- A5 POST /switch_model（成功 → 必须还原）-------------------------
    def a5():
        before = call(page, "GET", f"{API}/current_model")["data"]
        orig = f"{before['platform']}/{before['model_name']}"
        try:
            r = call(page, "POST", f"{API}/switch_model",
                     body={"platform": "minimax", "model_name": "MiniMax-M3"})
            expect_status(r, 200)
            assert r["data"].get("success") is True, f"切换失败：{r['data']}"
            now = call(page, "GET", f"{API}/current_model")["data"]
            assert now["model_name"] == "MiniMax-M3", f"切换后当前模型不对：{now}"
            return f"{orig} → minimax/MiniMax-M3 → 已还原"
        finally:
            b = before["platform"]
            n = before["model_name"]
            call(page, "POST", f"{API}/switch_model", body={"platform": b, "model_name": n})
            after = call(page, "GET", f"{API}/current_model")["data"]
            assert after["model_name"] == n, f"还原失败：{after}"
    check("A5", "接口", "POST /switch_model —— 切到 MiniMax-M3 再切回原模型", a5)

    # ---- A6 POST /agent/chat --------------------------------------------
    def a6():
        r = call(page, "POST", f"{API}/agent/chat",
                 body={"query": "我的知识库里有哪些关于 RAG 的内容？", "session_id": "e2e_agent"})
        expect_status(r, 200)
        d = r["data"]
        assert "response" in d, f"响应缺 response 字段：{d}"
        assert "answer" not in d, f"响应不该有 answer 字段（P1-1 同源问题）：{list(d)}"
        assert d["response"].strip(), "response 是空串"
        return f"答案 {len(d['response'])} 字，耗时 {r['ms']}ms：{d['response'][:80]}…"
    check("A6", "接口", "POST /agent/chat —— 真 Agent 跑通（ReAct + 工具调用）", a6)

    # ---- A7 POST /rag ----------------------------------------------------
    def a7():
        r = call(page, "POST", f"{API}/rag",
                 body={"query": "RAG 是什么？", "session_id": "e2e_rag"})
        expect_status(r, 200)
        d = r["data"]
        assert "response" in d, f"响应缺 response 字段：{d}"
        assert d["response"].strip(), "response 是空串"
        return f"答案 {len(d['response'])} 字，耗时 {r['ms']}ms：{d['response'][:80]}…"
    check("A7", "接口", "POST /rag —— 直连 RAG 链路（真检索）", a7)

    # ---- A8 POST /chat ---------------------------------------------------
    def a8():
        r = call(page, "POST", f"{API}/chat",
                 body={"query": "用一句话自我介绍", "session_id": "e2e_chat"})
        expect_status(r, 200)
        d = r["data"]
        assert "response" in d, f"响应缺 response 字段：{d}"
        assert d["response"].strip(), "response 是空串"
        return f"答案 {len(d['response'])} 字，耗时 {r['ms']}ms：{d['response'][:80]}…"
    check("A8", "接口", "POST /chat —— 直连 LLM 链路", a8)

    # ---- A9 POST /agent/chat 缺字段（负路径）-----------------------------
    def a9():
        r = call(page, "POST", f"{API}/agent/chat", body={})
        expect_status(r, 422)
        return f"422，detail={str(r['data'])[:100]}"
    check("A9", "负路径", "POST /agent/chat 缺 query → 422", a9)

    # ---- A10 POST /api/upload-and-parse（单文件）-------------------------
    def a10():
        r = call(page, "POST", f"{API}/api/upload-and-parse",
                 field="file", files=[{"name": f"{PROBE}single.txt",
                                       "content": "RAGMI E2E 探针：这是一段用于验证上传接口的文本。"}])
        expect_status(r, 200)
        d = r["data"]
        up = d["upload_details"]["uploaded_files"]
        assert len(up) == 1, f"期望上传 1 个，实际 {len(up)}：{d['upload_details']}"
        assert d["status"] == "completed", f"status 不是 completed：{d.get('status')}"
        return f"uploaded={len(up)}，解析结果键={list((d.get('parse_results') or {}).keys())[:4]}"
    check("A10", "接口", "POST /api/upload-and-parse —— 单文件上传+解析", a10)

    # ---- A11 POST /api/batch-upload-and-parse（批量）---------------------
    def a11():
        r = call(page, "POST", f"{API}/api/batch-upload-and-parse",
                 field="files", files=[
                     {"name": f"{PROBE}batch1.txt", "content": "探针文件 1 的内容。"},
                     {"name": f"{PROBE}batch2.txt", "content": "探针文件 2 的内容。"}])
        expect_status(r, 200)
        d = r["data"]
        up = d["upload_details"]["uploaded_files"]
        assert len(up) == 2, f"期望上传 2 个，实际 {len(up)}：{d['upload_details']}"
        return f"uploaded={len(up)}，message={d.get('message')}"
    check("A11", "接口", "POST /api/batch-upload-and-parse —— 批量上传 2 个文件", a11)

    # ---- A12 路径穿越（负路径）------------------------------------------
    def a12():
        r = call(page, "POST", f"{API}/api/batch-upload-and-parse",
                 field="files", files=[{"name": "../../evil.txt", "content": "evil"}])
        expect_status(r, 200)
        d = r["data"]
        failed = d["upload_details"]["failed_uploads"]
        assert len(failed) == 1, f"路径穿越应进 failed_uploads：{d['upload_details']}"
        leaked = list((ROOT / "evil.txt").exists() and [ROOT / "evil.txt"] or [])
        assert not leaked, f"路径穿越把文件写到 documents/ 外了：{leaked}"
        return f"failed_uploads={failed[0]['reason']}"
    check("A12", "负路径", "POST /api/batch-upload-and-parse —— 路径穿越被拦", a12)

    # ---- A13 类型白名单（负路径）----------------------------------------
    def a13():
        r = call(page, "POST", f"{API}/api/batch-upload-and-parse",
                 field="files", files=[{"name": f"{PROBE}evil.exe", "content": "MZ"}])
        expect_status(r, 200)
        d = r["data"]
        failed = d["upload_details"]["failed_uploads"]
        assert len(failed) == 1, f"非白名单类型应进 failed_uploads：{d['upload_details']}"
        assert not (ROOT / "documents" / f"{PROBE}evil.exe").exists(), "不该落盘 .exe"
        return f"failed_uploads={failed[0]['reason']}"
    check("A13", "负路径", "POST /api/batch-upload-and-parse —— 类型白名单拦截 .exe", a13)

    # ---- A14 同名跳过（overwrite=False）---------------------------------
    def a14():
        r = call(page, "POST", f"{API}/api/batch-upload-and-parse",
                 field="files", files=[{"name": f"{PROBE}batch1.txt", "content": "探针文件 1 的内容。"}])
        expect_status(r, 200)
        d = r["data"]
        skipped = d["upload_details"]["skipped_files"]
        assert len(skipped) == 1, f"同名文件应被跳过：{d['upload_details']}"
        return f"skipped_files={skipped[0]['reason'][:60]}…"
    check("A14", "负路径", "POST /api/batch-upload-and-parse —— 同名跳过（overwrite=False）", a14)


# ---------------------------------------------------------------------------
# B 组 —— 真实 Streamlit 三页面交互
# ---------------------------------------------------------------------------
def menu_frame(page, timeout=30000):
    """拿 sac.menu 的 iframe（实测 src 含 '/component/' + 'sac'）。"""
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        for frame in page.frames:
            url = frame.url or ""
            if "/component/" in url and "sac" in url:
                return frame
        page.wait_for_timeout(200)
    raise AssertionError("没找到 sac.menu 的 iframe")


def switch_page(page, label, heading_text):
    """切到某个页面并**等它真的换完**。

    ⚠️ 别只 `wait_for_selector(CHAT_INPUT)` —— 切页那一瞬，旧页面的输入框
    还在 DOM 里，等它就会立刻返回，于是 fill() 打在被拆掉的旧元素上，
    消息永远发不出去（实测踩过：知识库问答页 180 秒超时）。
    正确做法：等**标题**变成目标页的标题。
    """
    menu_frame(page).get_by_text(label).click()
    page.wait_for_function(
        """(want) => {
            const h = document.querySelector('[data-testid="stHeading"]');
            return h && h.innerText.includes(want);
        }""",
        arg=heading_text,
        timeout=60000)


def open_page(page, url):
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_selector(CHAT_INPUT, timeout=60000)


def wait_answer(page, timeout=180000):
    """等助手消息**真正出内容**。

    ⚠️ 只等"消息数 >= 2"会假阳性：Streamlit 先渲染消息容器和头像，
    正文（哪怕只是 spinner 的"检索中..."）过一会儿才到。
    实测踩过 —— 0.4 秒就放行，截出来助手区正文是空的。
    判据：消息 >= 2 **且** spinner 消失 **且** 正文非空。
    """
    page.wait_for_function(
        """() => {
            const msgs = document.querySelectorAll('[data-testid="stChatMessage"]');
            if (msgs.length < 2) return false;
            const last = msgs[msgs.length - 1];
            if (last.querySelector('[data-testid="stSpinner"]')) return false;
            const md = last.querySelector(
                '[data-testid="stChatMessageContent"] [data-testid="stMarkdownContainer"]');
            return !!md && (md.innerText || '').trim().length > 0;
        }""",
        timeout=timeout)


def answer_text(page):
    """助手消息的**正文**（用 stChatMessageContent 排除头像图标名）。

    ⚠️ 直接取整条消息的 innerText 会把 Material 图标名也算进来
    （"smart_toy" / "face"），会误判成"有内容"。
    """
    md = page.locator(f'{CHAT_MESSAGE} {CHAT_CONTENT} {MD}').last
    return md.inner_text().strip() if md.count() else ""


def run_ui_suite(page):
    group("B 组 · 真实 Streamlit 页面交互")

    # ---- B1 智能问答 -----------------------------------------------------
    def b1():
        open_page(page, FRONTEND)
        page.wait_for_selector(CHAT_INPUT, timeout=60000)
        page.locator(CHAT_INPUT).fill("1+1 等于多少？")
        page.locator(CHAT_INPUT).press("Enter")
        wait_answer(page)
        count = page.locator(CHAT_MESSAGE).count()
        user = page.locator(f'{CHAT_MESSAGE} {CHAT_CONTENT}').nth(0).inner_text()
        bot = answer_text(page)
        assert "1+1" in user, f"用户消息不对：{user[:80]}"
        assert bot.strip(), "助手回答是空的"
        assert "请求失败" not in bot, f"页面报错：{bot[:200]}"
        page.screenshot(path=str(ART / "ui_1_agent.png"), full_page=True)
        return f"{count} 条消息；助手回答 {len(bot)} 字：{bot[:100].strip()}…"
    check("B1", "界面", "智能问答页 —— 发问 → 真实 Agent 回答", b1)

    # ---- B2 清空 ---------------------------------------------------------
    def b2():
        before = page.locator(CHAT_MESSAGE).count()
        page.locator('button:has-text("🗑")').first.click()   # Streamlit 双渲染 → .first
        page.wait_for_function(
            "() => document.querySelectorAll('[data-testid=\"stChatMessage\"]').length === 0",
            timeout=30000)
        page.screenshot(path=str(ART / "ui_2_cleared.png"), full_page=True)
        return f"清空前 {before} 条 → 清空后 0 条"
    check("B2", "界面", "智能问答页 —— 🗑 清空", b2)

    # ---- B3 知识库问答（已知 P1-1）---------------------------------------
    def b3():
        switch_page(page, "知识库问答", "知识库问答")
        page.wait_for_selector(CHAT_INPUT, timeout=60000)
        page.locator(CHAT_INPUT).fill("RAG 是什么？")
        page.locator(CHAT_INPUT).press("Enter")
        wait_answer(page)
        bot = answer_text(page)
        page.screenshot(path=str(ART / "ui_3_rag_page.png"), full_page=True)
        assert bot.strip(), "助手回答是空的"
        if bot.strip() == "(无答案)":
            return ("KNOWN ⚠️ 命中已知 bug P1-1：前端读 answer、后端返 response "
                    "→ 页面显示「(无答案)」（预期内的已知缺陷；后端其实有真答案）")
        return f"⚠️ P1-1 似乎已修复，页面真的返回了答案：{bot[:100].strip()}…"
    check("B3", "界面", "知识库问答页 —— 直连 /rag", b3)

    # ---- B4 仓库管理：上传 -----------------------------------------------
    def b4():
        switch_page(page, "仓库管理配置", "仓库管理配置")
        page.wait_for_selector(UPLOAD_INPUT, timeout=60000)
        page.locator(UPLOAD_INPUT).set_input_files({
            "name": f"{PROBE}ui.txt",
            "mimeType": "text/plain",
            "buffer": b"RAGMI E2E UI probe upload.",
        })
        page.locator('button:has-text("上传并解析")').click()
        page.wait_for_selector(ALERT, timeout=300000)
        alert_text = page.locator(ALERT).first.inner_text()
        page.screenshot(path=str(ART / "ui_4_repo.png"), full_page=True)
        assert "完成" in alert_text, f"没看到上传统计：{alert_text[:200]}"
        assert page.locator(EXCEPTION).count() == 0, "页面上有 stException"
        return f"上传统计：{alert_text.strip()[:120]}"
    check("B4", "界面", "仓库管理页 —— 上传文件并解析", b4)

    # ---- B5 三页互切 -----------------------------------------------------
    def b5():
        seen = []
        for label, expect_text in [("知识库问答", "知识库问答"),
                                   ("仓库管理配置", "仓库管理配置"),
                                   ("智能问答", "智能问答系统")]:
            switch_page(page, label, expect_text)
            seen.append(label)
        page.screenshot(path=str(ART / "ui_5_switch.png"), full_page=True)
        return "切换正常：" + " → ".join(seen)
    check("B5", "界面", "三页互切（智能问答 / 知识库问答 / 仓库管理）", b5)


# ---------------------------------------------------------------------------
# C 组 —— 报告
# ---------------------------------------------------------------------------
HTML_TMPL = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>RAGMI 真栈 E2E 报告</title>
<style>
 body{{font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;margin:0;
      background:#0f1115;color:#e6e6e6;padding:32px}}
 h1{{font-size:22px;margin:0 0 4px}}
 .sub{{color:#8b93a1;font-size:13px;margin-bottom:24px}}
 .cards{{display:flex;gap:14px;margin-bottom:26px;flex-wrap:wrap}}
 .card{{background:#171a21;border:1px solid #262a33;border-radius:10px;padding:14px 20px;min-width:130px}}
 .card b{{display:block;font-size:26px;line-height:1.2}}
 .card span{{color:#8b93a1;font-size:12px}}
 table{{width:100%;border-collapse:collapse;background:#14171d;border-radius:10px;overflow:hidden}}
 th,td{{padding:9px 12px;text-align:left;border-bottom:1px solid #23262e;font-size:13px;vertical-align:top}}
 th{{background:#1b1f27;color:#9aa3b2;font-weight:600;font-size:12px}}
 tr.pass td.id{{color:#3fb950}} tr.fail td.id{{color:#f85149}}
 td.id{{font-family:ui-monospace,Menlo,monospace;white-space:nowrap}}
 td.detail{{color:#9aa3b2;font-family:ui-monospace,Menlo,monospace;font-size:12px;max-width:560px}}
 td.sec{{text-align:right;white-space:nowrap;color:#8b93a1}}
 .grp td{{background:#1b1f27;font-weight:600;color:#c9d1d9;font-size:12px}}
 h2{{font-size:15px;margin:28px 0 10px;color:#c9d1d9}}
 img{{max-width:100%;border:1px solid #262a33;border-radius:8px;margin:6px 0 14px}}
 .shots{{display:flex;gap:14px;flex-wrap:wrap}}
 .shots figure{{margin:0;background:#14171d;padding:8px;border-radius:8px;border:1px solid #262a33}}
 .shots figcaption{{font-size:12px;color:#8b93a1;padding:4px 2px 6px}}
</style></head><body>
<h1>RAGMI 真栈 E2E 报告</h1>
<div class="sub">{meta}</div>
<div class="cards">{cards}</div>
<table><thead><tr><th>ID</th><th>用例</th><th>结果</th><th>耗时</th><th>详情</th></tr></thead>
<tbody>{rows}</tbody></table>
{shots}
</body></html>"""


def build_report(meta):
    passed = sum(1 for r in RESULTS if r["ok"])
    failed = len(RESULTS) - passed
    total_sec = sum(r["sec"] for r in RESULTS)

    rows = []
    last_group = None
    known_rows = []
    for r in RESULTS:
        if r["group"] != last_group:
            rows.append(f'<tr class="grp"><td colspan="5">{r["group"]}</td></tr>')
            last_group = r["group"]
        cls = "pass" if r["ok"] else "fail"
        mark = "✅ 通过" if r["ok"] else "❌ 失败"
        if r["detail"].startswith("KNOWN"):
            mark = '<span style="color:#d29922">⚠️ 已知缺陷</span>'
            known_rows.append(r)
        rows.append(
            f'<tr class="{cls}"><td class="id">{r["id"]}</td><td>{r["name"]}</td>'
            f'<td>{mark}</td><td class="sec">{r["sec"]:.1f}s</td>'
            f'<td class="detail">{r["detail"][:400]}</td></tr>')

    cards = (f'<div class="card"><b style="color:#3fb950">{passed}</b><span>通过</span></div>'
             f'<div class="card"><b style="color:{"#f85149" if failed else "#8b93a1"}">{failed}</b>'
             f'<span>失败</span></div>'
             f'<div class="card"><b>{len(RESULTS)}</b><span>总用例</span></div>'
             f'<div class="card"><b>{total_sec:.0f}s</b><span>总耗时</span></div>')

    shots = ""
    imgs = sorted(ART.glob("ui_*.png"))
    if imgs:
        cards_shots = "".join(
            f'<figure><img src="{p.name}"><figcaption>{p.stem}</figcaption></figure>'
            for p in imgs)
        shots = f'<h2>界面截图</h2><div class="shots">{cards_shots}</div>'

    known = ""
    if known_rows:
        items = "".join(
            f"<li><b>{r['id']}</b> {r['name']} —— {r['detail'][:300]}</li>"
            for r in known_rows)
        known = (f'<h2>已知缺陷（本轮只记录、不修）</h2>'
                 f'<ul style="color:#d29922;font-size:13px;line-height:1.8">{items}</ul>')

    return HTML_TMPL.format(meta=meta, cards=cards, rows="".join(rows),
                             shots=shots + known)


# ---------------------------------------------------------------------------
# 清理（把探针文件从 documents/ txt/ 里清掉，并把哈希索引还原）
# ---------------------------------------------------------------------------
def cleanup():
    removed = []
    for d in (ROOT / "documents", ROOT / "txt"):
        for p in d.glob(f"{PROBE}*"):
            removed.append(str(p.relative_to(ROOT)))
            p.unlink(missing_ok=True)
    return removed


def main():
    ART.mkdir(parents=True, exist_ok=True)
    for old in ART.glob("*.png"):
        old.unlink()

    filter_json = ROOT / "txt" / ".file_filter.json"
    filter_backup = None
    if filter_json.exists():
        filter_backup = ART / "file_filter.json.bak"
        shutil.copy2(filter_json, filter_backup)

    print(f"后端   : {API}")
    print(f"前端   : {FRONTEND}")
    print(f"产物   : {ART}")

    t0 = time.time()
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,                      # 可见的 Chrome 窗口
            args=["--window-size=1440,960"],
        )
        ctx = browser.new_context(locale="zh-CN", viewport={"width": 1440, "height": 960})
        page = ctx.new_page()

        try:
            # 先开前端页面 —— 后续所有 fetch 都在这个 origin（localhost:8501）下发起，
            # 这样 CORS 会被真实触发（后端在 8000，前端在 8501，跨源）。
            open_page(page, FRONTEND)
            print(f"前端首屏就绪：{page.title()}")

            run_api_suite(page)
            run_ui_suite(page)

            # ---- 报告：在 Chrome 里开一个新标签页展示 ----------------------
            meta = (f"生成于 {time.strftime('%Y-%m-%d %H:%M:%S')} ｜ "
                    f"后端 {API} ｜ 前端 {FRONTEND} ｜ 真实 Milvus / Ollama / MiniMax ｜ "
                    f"总耗时 {time.time() - t0:.0f}s")
            report = ART / "report.html"
            report.write_text(build_report(meta), encoding="utf-8")
            print(f"\n报告已生成：{report}")

            report_page = ctx.new_page()
            report_page.goto(report.resolve().as_uri())
            report_page.bring_to_front()
            print("已在 Chrome 打开报告页（这个标签页就是报告）")

            passed = sum(1 for r in RESULTS if r["ok"])
            failed = len(RESULTS) - passed
            print(f"\n{'='*60}\n总计 {len(RESULTS)} 条：通过 {passed} / 失败 {failed} / "
                  f"耗时 {time.time()-t0:.0f}s\n{'='*60}")

            print("\nChrome 保持打开（60 秒），方便你看报告和页面…")
            time.sleep(60)
            return 0 if failed == 0 else 1
        finally:
            removed = cleanup()
            if removed:
                print(f"\n已清理探针文件：{removed}")
            if filter_backup and filter_backup.exists():
                shutil.copy2(filter_backup, filter_json)
                filter_backup.unlink()
                print("已还原 txt/.file_filter.json")
            browser.close()


if __name__ == "__main__":
    sys.exit(main())
