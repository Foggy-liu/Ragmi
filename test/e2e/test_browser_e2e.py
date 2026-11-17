"""test/e2e/test_browser_e2e.py —— L4 浏览器 E2E。

跑法：
    pytest -m e2e -v --tracing=retain-on-failure

主体：conftest 起的**进程外假后端** + **专用** Streamlit（8511，注入 API_BASE_URL）。
⚠️ 不复用用户已开的 Streamlit —— 复用来的进程没有 env 注入，拦截会失效。
"""
import time
from pathlib import Path

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e

# Streamlit 1.52 的 DOM testid（已在安装包的前端 bundle 里核实存在）
CHAT_INPUT = '[data-testid="stChatInputTextArea"]'
CHAT_MESSAGE = '[data-testid="stChatMessage"]'
CHAT_INPUT_BOX = '[data-testid="stChatInput"]'
UPLOAD_INPUT = '[data-testid="stFileUploaderDropzoneInput"]'
ALERT = '[data-testid="stAlert"]'
HEADING = '[data-testid="stHeading"]'
EXCEPTION = '[data-testid="stException"]'


def open_page(page, url):
    """打开页面并等首屏渲染完。

    Streamlit 要把整个脚本跑完才出内容 —— 首屏超时给到 60 秒。
    """
    page.goto(url, wait_until="domcontentloaded")
    expect(page.locator(CHAT_INPUT)).to_be_visible(timeout=60000)


def menu_frame(page, timeout=30000):
    """拿到 sac.menu 的 frame。

    ⚠️ 菜单渲染在 iframe 里。**实测**（streamlit_antd_components 当前版本）
    src 形如：
        /component/streamlit_antd_components.utils.component_func.sac/index.html?streamlitUrl=...
    不是设计文档里假设的 /component/sac.<hash>/index.html —— 那个模式永远匹配不上。
    所以只按 "/component/" + "sac" 两个特征匹配，不写死完整路径。
    """
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        for frame in page.frames:
            url = frame.url or ""
            if "/component/" in url and "sac" in url:
                return frame
        page.wait_for_timeout(200)
    raise AssertionError("没找到 sac.menu 的 iframe（页面可能没加载完）")


def ask_question(page, text):
    """在聊天框里发一条消息。"""
    box = page.locator(CHAT_INPUT)
    box.fill(text)
    box.press("Enter")


# ---------------------------------------------------------------------------
# E1–E7
# ---------------------------------------------------------------------------

def test_e1_chat_shows_user_and_assistant_messages(page, streamlit_url, fake_backend):
    """智能问答：发问 → 出现用户消息 + 助手答案。"""
    fake_backend.agent_answer = "E1 假后端答案"
    open_page(page, streamlit_url)

    ask_question(page, "你好")

    expect(page.locator(CHAT_MESSAGE)).to_have_count(2, timeout=60000)
    expect(page.locator(CHAT_MESSAGE).nth(0)).to_contain_text("你好")
    expect(page.locator(CHAT_MESSAGE).nth(1)).to_contain_text("E1 假后端答案")


def test_e2_clear_button_resets_messages(page, streamlit_url, fake_backend):
    """智能问答：🗑 清空 → 消息归零。"""
    open_page(page, streamlit_url)

    ask_question(page, "你好")
    expect(page.locator(CHAT_MESSAGE)).to_have_count(2, timeout=60000)

    # ⚠️ Streamlit 把每个 st.button 渲染**两次**（一次在底部固定容器里可见，
    # 一次在主区里隐藏）。不加 .first 会撞 Playwright strict mode。
    page.locator('button:has-text("🗑")').first.click()

    expect(page.locator(CHAT_MESSAGE)).to_have_count(0, timeout=30000)


def test_e3_settings_button_does_not_crash(page, streamlit_url, fake_backend):
    """智能问答：⚙ 点击不报错（功能未实现，只断言不崩）。"""
    open_page(page, streamlit_url)

    # ⚠️ 同 E2：Streamlit 双渲染，必须取第一个（可见的那个）。
    page.locator('button:has-text("⚙")').first.click()
    page.wait_for_timeout(1500)

    expect(page.locator(EXCEPTION)).to_have_count(0)


def test_e4_kb_page_shows_answer(page, streamlit_url, fake_backend):
    """知识库问答：假后端返回真实契约 {"response": ...} → 页面应显示该答案。

    ⚠️ 假后端**必须**返回 response 而不是 answer —— 后端契约是 ChatResponse{response}。
    （P1-1 修复前前端读 .get("answer")，页面永远显示「(无答案)」。）

    ⚠️ 切页后必须**等标题变了**再碰输入框：旧页面的输入框在切页那一瞬还在 DOM 里，
    等它可见会立刻返回，于是 fill() 打在被拆掉的旧元素上，消息永远发不出去
    （实测页面上 0 条消息）。跟 E6 同一个套路。
    """
    open_page(page, streamlit_url)
    menu_frame(page).get_by_text("知识库问答").click()
    expect(page.locator(HEADING).first).to_contain_text("知识库问答", timeout=60000)

    ask_question(page, "知识库里有什么")

    expect(page.locator(CHAT_MESSAGE)).to_have_count(2, timeout=60000)
    expect(page.locator(CHAT_MESSAGE).nth(1)).to_contain_text(fake_backend.rag_answer)
    expect(page.locator(CHAT_MESSAGE).nth(1)).not_to_contain_text("(无答案)")


def test_e5_upload_shows_stats(page, streamlit_url, fake_backend):
    """仓库管理：传文件 → 上传并解析 → 出统计，且数量 > 0。"""
    fake_backend.uploaded_count = 2
    open_page(page, streamlit_url)
    menu_frame(page).get_by_text("仓库管理配置").click()

    expect(page.locator(UPLOAD_INPUT)).to_be_attached(timeout=60000)
    page.locator(UPLOAD_INPUT).set_input_files({
        "name": "probe.txt",
        "mimeType": "text/plain",
        "buffer": b"hello",
    })

    page.locator('button:has-text("上传并解析")').click()

    expect(page.locator(ALERT)).to_contain_text("完成：2 个上传", timeout=60000)


def test_e6_switch_between_three_pages(page, streamlit_url, fake_backend):
    """菜单：三页互切。

    ⚠️ 每个页面都渲染**不止一个** stHeading（`st.title` + `st.subheader` 都是
    `data-testid="stHeading"`）→ 必须取 `.first`（`st.title` 在前），否则撞
    Playwright strict mode。`.first` 每次重试都会重新求值，所以切页的
    渲染延迟会被自动等掉。
    """
    open_page(page, streamlit_url)

    menu_frame(page).get_by_text("知识库问答").click()
    expect(page.locator(HEADING).first).to_contain_text("知识库问答", timeout=60000)

    menu_frame(page).get_by_text("仓库管理配置").click()
    expect(page.locator(HEADING).first).to_contain_text("仓库管理配置", timeout=60000)

    menu_frame(page).get_by_text("智能问答").click()
    expect(page.locator(HEADING).first).to_contain_text("智能问答系统", timeout=60000)


def test_e7_backend_500_shows_error_not_blank_page(page, streamlit_url, fake_backend):
    """智能问答：后端返回 500 → 页面显示"请求失败"，不白屏。"""
    fake_backend.agent_status = 500
    open_page(page, streamlit_url)

    ask_question(page, "你好")

    expect(page.locator(CHAT_MESSAGE)).to_have_count(2, timeout=60000)
    expect(page.locator(CHAT_MESSAGE).nth(1)).to_contain_text("请求失败")
    expect(page.locator(EXCEPTION)).to_have_count(0)


# ---------------------------------------------------------------------------
# E8 · 真联调冒烟（真后端 + 真 MiniMax）
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_e8_real_backend_smoke(page):
    """真联调：专用 Streamlit 指向**真后端**（8000）+ 真 MiniMax。

    真后端没起 → skip（不硬失败）。CI 里没真环境时这一条会被跳过。
    """
    import os
    import subprocess
    import sys
    import urllib.request

    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/debug/simple", timeout=3) as resp:
            assert resp.status == 200
    except Exception as exc:                       # noqa: BLE001
        pytest.skip(f"真后端未启动（8000）：{exc}")

    port = 8512
    env = os.environ.copy()
    env["API_BASE_URL"] = "http://127.0.0.1:8000"
    env["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run", "main_web.py",
            "--server.port", str(port),
            "--server.address", "127.0.0.1",
            "--server.headless", "true",
        ],
        cwd=str(Path(__file__).resolve().parent.parent.parent),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.time() + 90
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=3):
                    break
            except Exception:                      # noqa: BLE001
                time.sleep(0.5)
        else:
            pytest.fail("Streamlit 启动超时")

        page.goto(f"http://127.0.0.1:{port}", wait_until="domcontentloaded")
        expect(page.locator(CHAT_INPUT)).to_be_visible(timeout=60000)
        ask_question(page, "1+1等于多少")

        expect(page.locator(CHAT_MESSAGE)).to_have_count(2, timeout=120000)
        expect(page.locator(CHAT_MESSAGE).nth(1)).not_to_contain_text("请求失败")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
