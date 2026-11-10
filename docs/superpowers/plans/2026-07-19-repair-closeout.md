# RAGMI 修复收尾实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 RAGMI 项目带到"面试官 30 分钟内能跑通、能读懂、能问得下去"的水平

**Architecture:** 4 个串行里程碑（M1 → M2 → M3 → M4），每个独立可验证。每个里程碑通过 `make milestone-N` 或文档中给出的命令验证通过后才进入下一个。

**Tech Stack:** FastAPI + LangGraph + Streamlit + Milvus + pymilvus 2.6.14 + MiniMax-M3 (LLM) + pytest

**Spec 参考:** `docs/superpowers/specs/2026-07-19-repair-closeout-design.md`

---

## 文件变更地图

### 创建（10 个）
- `requirements-dev.txt`
- `.env.example`
- `docs/superpowers/plans/2026-07-19-repair-closeout.md`（本文件）
- `utils/logging.py`
- `web_page/repo_admin.py`
- `pytest.ini`
- `Makefile`
- `documents/.gitkeep`（已存在）
- `txt/.gitkeep`（已存在）

### 修改（15 个）
- `requirements.txt`（锁版本）
- `Dockerfile`（修启动命令）
- `docker-compose.yml`（重写为 3 service）
- `main.py`（挂 router + lifespan）
- `main_web.py`（3 页面布局）
- `api/api_file.py`（路径穿越 + 类型白名单）
- `utils/models/embedding_model.py`（修 config 路径）
- `core/rags/rags.py`（删 fallback + 加 logger）
- `utils/txt_spliter/vector_main.py`（alias swap）
- `agent/runtime.py`（print → logger）
- `agent/nodes/agent.py`（print → logger）
- `agent/nodes/reflect.py`（print → logger）
- `test/agent_test_cases.json`（T06 改 chat）
- `test/run_agent_eval.py`（status 字段 + --mock）
- `CLAUDE.md`（重写架构章节）
- `README.md`（Docker + 测试章节）
- `.gitignore`（已部分更新）

### 删除（5 个）
- `docker-compose-milvus.yml`
- `docker-compose-offline.yml`
- `compose.yaml`
- `web_page/knowledge_base.py`
- `web_page/mcp_page.py`
- `test/test_agent.py`

---

# 阶段 1：M1 可运行基线

## Task 1.1：锁定 requirements.txt 版本

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1：生成当前能跑的 lock 文件作为参考**

```bash
pip freeze > /tmp/ragmi.lock
head -30 /tmp/ragmi.lock
```

- [ ] **Step 2：用 pip freeze 提取关键依赖的具体版本**

从 `/tmp/ragmi.lock` 中提取以下包（替换 `<VERSION>` 为实际值）：

```
fastapi==<VERSION>
pydantic==<VERSION>
uvicorn==<VERSION>
streamlit==<VERSION>
pymilvus==<VERSION>
streamlit-antd-components==<VERSION>
openai==<VERSION>
langgraph==<VERSION>
langchain-core==<VERSION>
langchain-openai==<VERSION>
langsmith==<VERSION>
python-docx==<VERSION>
python-dotenv==<VERSION>
pyyaml==<VERSION>
```

- [ ] **Step 3：重写 requirements.txt**

完整内容（替换 `<VERSION>` 为 Step 2 的值）：

```txt
fastapi==<VERSION>
pydantic==<VERSION>
uvicorn==<VERSION>
streamlit==<VERSION>
pymilvus==<VERSION>
streamlit-antd-components==<VERSION>
openai==<VERSION>
langgraph==<VERSION>
langchain-core==<VERSION>
langchain-openai==<VERSION>
langsmith==<VERSION>
python-docx==<VERSION>
python-dotenv==<VERSION>
pyyaml==<VERSION>
pymupdf
pytesseract
opencv-python
numpy
pillow
markdown
beautifulsoup4
```

- [ ] **Step 4：验证依赖能装**

```bash
pip install -r requirements.txt
```

Expected: 无报错。

- [ ] **Step 5：Commit**

```bash
git add requirements.txt
git commit -m "chore: lock requirements.txt versions for reproducible builds"
```

---

## Task 1.2：创建 requirements-dev.txt

**Files:**
- Create: `requirements-dev.txt`

- [ ] **Step 1：创建文件**

文件内容：

```txt
-r requirements.txt
pytest>=8.0
pytest-cov>=5.0
```

- [ ] **Step 2：验证 dev 依赖能装**

```bash
pip install -r requirements-dev.txt
pytest --version
```

Expected: `pytest 8.x.x`

- [ ] **Step 3：Commit**

```bash
git add requirements-dev.txt
git commit -m "chore: add requirements-dev.txt (pytest + pytest-cov)"
```

---

## Task 1.3：修复 Dockerfile 启动命令

**Files:**
- Modify: `Dockerfile`（line 14）

- [ ] **Step 1：修改 CMD 行**

将：
```dockerfile
CMD ["uvicorn", "api.api_file:app", "--host", "0.0.0.0", "--port", "8000"]
```

改为：
```dockerfile
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2：本地验证 Docker build 能成功**

```bash
docker build -t ragmi:test .
```

Expected: build 成功，无报错。

- [ ] **Step 3：Commit**

```bash
git add Dockerfile
git commit -m "fix(dockerfile): point CMD to main:app (was api.api_file:app)"
```

---

## Task 1.4：重写 docker-compose.yml 为 3 service

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1：用以下内容覆盖文件**

```yaml
version: "3.8"

services:
  milvus:
    image: milvusdb/milvus:v2.4.0
    container_name: ragmi-milvus
    ports:
      - "19530:19530"
      - "9091:9091"
    environment:
      ETCD_USE_EMBED_STORAGE: "true"
      COMMON_SECURITY_AUTHORIZATIONENABLED: "false"
    volumes:
      - milvus-data:/var/lib/milvus
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9091/healthz"]
      interval: 30s
      timeout: 20s
      retries: 3
      start_period: 90s
    networks:
      - ragmi-net

  api:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: ragmi-api
    ports:
      - "8000:8000"
    environment:
      MILVUS_HOST: milvus
      MILVUS_PORT: 19530
      LLM_ROOT: /app
    env_file:
      - .env
    volumes:
      - ./documents:/app/documents
      - ./txt:/app/txt
    depends_on:
      milvus:
        condition: service_healthy
    networks:
      - ragmi-net
    extra_hosts:
      - "host.docker.internal:host-gateway"

  web:
    image: python:3.11-slim
    container_name: ragmi-web
    working_dir: /app
    command: >
      bash -c "pip install --no-cache-dir -r requirements.txt streamlit &&
               streamlit run main_web.py --server.address 0.0.0.0 --server.port 8501"
    ports:
      - "8501:8501"
    volumes:
      - .:/app
    environment:
      API_BASE_URL: http://api:8000
    depends_on:
      - api
    networks:
      - ragmi-net

volumes:
  milvus-data:

networks:
  ragmi-net:
    driver: bridge
```

- [ ] **Step 2：验证 compose 文件语法**

```bash
docker compose config -q
```

Expected: 无输出，退出码 0。

- [ ] **Step 3：Commit**

```bash
git add docker-compose.yml
git commit -m "refactor(docker): unify compose to 3 services (milvus/api/web)"
```

---

## Task 1.5：删除废弃 compose 文件

**Files:**
- Delete: `docker-compose-milvus.yml`, `docker-compose-offline.yml`, `compose.yaml`

- [ ] **Step 1：删除文件**

```bash
git rm docker-compose-milvus.yml docker-compose-offline.yml compose.yaml
```

- [ ] **Step 2：Commit**

```bash
git commit -m "chore: remove obsolete compose files"
```

---

## Task 1.6：创建 .env.example

**Files:**
- Create: `.env.example`

- [ ] **Step 1：创建文件**

```bash
# ===== LLM (MiniMax) =====
MINIMAX_BASE_URL=https://api.minimax.chat/v1
MINIMAX_API_KEY=<your_key_here>

# ===== LLM (Aliyun 备选) =====
ALIYUN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
ALIYUN_API_KEY=<your_key_here>

# ===== Ollama (本地 embedding) =====
OLLAMA_BASE_URL=http://host.docker.internal:11434
# 在 docker compose 内，host.docker.internal 解析到宿主机
# 裸跑时改为 http://localhost:11434

# ===== Milvus =====
# compose 内用 milvus（service 名），裸跑用 localhost
MILVUS_HOST=milvus
MILVUS_PORT=19530
MILVUS_COLLECTION=langchain

# ===== LangSmith（可选） =====
LANGSMITH_TRACING=false
LANGSMITH_API_KEY=<your_key_here>
LANGSMITH_PROJECT=ragmi

# ===== Embedding =====
EMBEDDING_PROVIDER=ollama
EMBEDDING_MODEL=bge-large
EMBEDDING_DIM=1024
```

- [ ] **Step 2：验证文件不被 git 跟踪 secrets**

```bash
cat .gitignore | grep -E "^\.env$|^\.env\.local$"
```

Expected: 至少一行匹配 `.env`。

- [ ] **Step 3：Commit**

```bash
git add .env.example
git commit -m "docs: add .env.example template"
```

---

## Task 1.7：M1 验证

- [ ] **Step 1：复制 .env.example 为 .env 并填入真实 key**

```bash
cp .env.example .env
# 编辑 .env，填入 MINIMAX_API_KEY（至少这一个）
```

- [ ] **Step 2：启动 compose**

```bash
docker compose up -d
```

Expected: 三个 service 都 healthy。

- [ ] **Step 3：验证后端存活**

```bash
sleep 30
curl -s http://localhost:8000/debug/simple
```

Expected: 返回 JSON，包含 `当前模型` 字段。

- [ ] **Step 4：验证前端存活**

浏览器访问 `http://localhost:8501`，看到 Streamlit 页面。

- [ ] **Step 5：清理**

```bash
docker compose down
```

**M1 通过标准**：上述命令零报错，`/debug/simple` 返回 200。

---

# 阶段 2：M2 上传 → RAG 闭环

## Task 2.1：挂载 api_file 路由到 main.py

**Files:**
- Modify: `main.py`

- [ ] **Step 1：在 imports 后追加 router 挂载**

修改 `main.py` line 9 后追加：

```python
from api.api_file import appfile
```

修改 line 28（router 挂载块）后追加：

```python
app.include_router(appfile, prefix="/api", tags=["file"])
```

完整 `main.py`：

```python
from fastapi import FastAPI, Request
from uvicorn import run

from utils.models.model_manager import ModelManager
from utils.models.model_setting import LLMmodel

from api.api_chat import appchat
from api.api_model import appmodel
from api.api_rag import apprag
from api.api_agent import appagent
from api.api_file import appfile

app = FastAPI()

model_manager = ModelManager()
model_manager.load_config_models()

default_model = LLMmodel.create_minimax()
model_manager.set_current_model(default_model)

app.state.model_manager = model_manager

app.include_router(appchat, tags=["chat"])
app.include_router(appmodel, tags=["model"])
app.include_router(apprag, tags=["rag"])
app.include_router(appagent, tags=["agent"])
app.include_router(appfile, prefix="/api", tags=["file"])


@app.get("/debug/simple")
async def debug_simple(request: Request):
    result = {
        "app.state类型": type(request.app.state).__name__,
        "是否有model_manager": hasattr(request.app.state, "model_manager"),
    }
    if hasattr(request.app.state, "model_manager"):
        mgr = request.app.state.model_manager
        result.update({
            "当前模型": f"{mgr.current_model.platform}-{mgr.current_model.model_name}" if mgr.current_model else "None",
            "可用模型数量": len(mgr.available_models),
            "已实例化模型": list(mgr.instantiated_models.keys()),
        })
    return result


if __name__ == "__main__":
    run(app, host="127.0.0.1", port=8000)
```

- [ ] **Step 2：验证语法**

```bash
python -c "import ast; ast.parse(open('main.py').read())"
```

Expected: 无输出。

- [ ] **Step 3：Commit**

```bash
git add main.py
git commit -m "fix(main): mount api_file router at /api prefix"
```

---

## Task 2.2：添加路径穿越校验到 api_file.py

**Files:**
- Modify: `api/api_file.py`（在 batch_upload_and_parse 函数开头）

- [ ] **Step 1：在 batch_upload_and_parse 循环内增加路径校验**

修改 `api/api_file.py`，在 `for file in files:` 之后、`file_suffix = ...` 之前加入校验逻辑：

修改 line 47 后（在 `save_path = input_dir / save_filename` 之后、`if file_suffix not in SUPPORTED_FILE_TYPES:` 之前）插入：

```python
        # 路径穿越校验：resolve() 后必须在 input_dir 内
        try:
            resolved = (input_dir / save_filename).resolve()
            input_dir_resolved = input_dir.resolve()
            if not str(resolved).startswith(str(input_dir_resolved)):
                failed_uploads.append({
                    "filename": file.filename,
                    "reason": "文件名包含非法路径字符"
                })
                continue
        except Exception:
            failed_uploads.append({
                "filename": file.filename,
                "reason": "路径解析失败"
            })
            continue
```

- [ ] **Step 2：验证语法**

```bash
python -c "import ast; ast.parse(open('api/api_file.py').read())"
```

Expected: 无输出。

- [ ] **Step 3：手测路径穿越被拒绝**

启动后端后：
```bash
curl -X POST http://localhost:8000/api/batch-upload-and-parse \
  -F "files=@main.py;filename=../../../etc/passwd"
```

Expected: response 中 `failed_uploads` 包含 `../etc/passwd`，reason 为"文件名包含非法路径字符"。

- [ ] **Step 4：Commit**

```bash
git add api/api_file.py
git commit -m "fix(api): add path traversal validation to upload endpoint"
```

---

## Task 2.3：收紧文件类型白名单

**Files:**
- Modify: `api/api_file.py` line 25

- [ ] **Step 1：修改 SUPPORTED_FILE_TYPES**

将：
```python
SUPPORTED_FILE_TYPES = {".txt", ".md", ".docx", ".doc", ".pdf"}
```

改为：
```python
SUPPORTED_FILE_TYPES = {".txt", ".md", ".docx", ".pdf"}
```

（移除 `.doc`——旧版 Word 格式；保留 .pdf/.docx/.md/.txt）

- [ ] **Step 2：Commit**

```bash
git add api/api_file.py
git commit -m "fix(api): drop .doc from whitelist (legacy format)"
```

---

## Task 2.4：修复 embedding_model.py 配置读取路径

**Files:**
- Modify: `utils/models/embedding_model.py` line 92

- [ ] **Step 1：修改 get_milvus_config 中的读取路径**

将：
```python
        milvus_config = embed_config.get("milvus", {}).copy()
```

改为：
```python
        vector_store = embed_config.get("vector_store", {})
        milvus_config = vector_store.get("milvus", {}).copy()
        if not milvus_config:
            raise ValueError(
                "EMBEDDING_CONFIG.vector_store.milvus 配置缺失或为空，"
                "请检查 configs/model_config.yaml"
            )
```

- [ ] **Step 2：验证语法**

```bash
python -c "import ast; ast.parse(open('utils/models/embedding_model.py').read())"
```

Expected: 无输出。

- [ ] **Step 3：Commit**

```bash
git add utils/models/embedding_model.py
git commit -m "fix(embed): read milvus config from correct YAML path"
```

---

## Task 2.5：移除 core/rags/rags.py 硬编码 fallback

**Files:**
- Modify: `core/rags/rags.py` line 41-46（fallback 块）

- [ ] **Step 1：先读文件确认 fallback 块位置**

```bash
grep -n "fallback\|MILVUS\|milvus" core/rags/rags.py | head -20
```

- [ ] **Step 2：删除 fallback 逻辑块**

打开 `core/rags/rags.py`，找到形如下面的代码：

```python
    # fallback values
    host = milvus_config.get("host", "localhost")
    port = milvus_config.get("port", 19530)
    collection = milvus_config.get("collection", "langchain")
```

替换为：

```python
    # fail-loud: 配置缺失立刻报错，不掩盖
    try:
        host = milvus_config["host"]
        port = milvus_config["port"]
        collection = milvus_config["collection"]
    except KeyError as e:
        raise ConfigError(
            f"Milvus 配置缺失字段 {e}，请检查 configs/model_config.yaml 的 "
            "EMBEDDING_CONFIG.vector_store.milvus 节"
        ) from e
```

并在文件顶部 import 区域加：

```python
class ConfigError(Exception):
    """配置错误，启动期应 fail-fast。"""
    pass
```

- [ ] **Step 3：验证语法**

```bash
python -c "import ast; ast.parse(open('core/rags/rags.py').read())"
```

Expected: 无输出。

- [ ] **Step 4：Commit**

```bash
git add core/rags/rags.py
git commit -m "fix(rag): remove silent config fallback, fail-loud instead"
```

---

## Task 2.6：实现 Milvus alias swap 安全重建

**Files:**
- Modify: `utils/txt_spliter/vector_main.py`（找到重建/重建集合的函数）

- [ ] **Step 1：找到现有重建函数**

```bash
grep -n "drop_collection\|create_collection\|rebuild" utils/txt_spliter/vector_main.py
```

- [ ] **Step 2：用 alias swap 替换 drop+create**

找到形如 `client.drop_collection(...); client.create_collection(...)` 的代码块，替换为：

```python
    import time
    from pymilvus import MilvusClient

    ALIAS_NAME = "langchain"
    new_collection_name = f"langchain_{int(time.time())}"

    # 1. 创建新集合
    client.create_collection(
        collection_name=new_collection_name,
        dimension=dim,
        **collection_kwargs,
    )

    # 2. 灌入所有新 chunks（这部分逻辑保持不变，只是目标集合名换为 new_collection_name）
    # ... ingest_all_chunks(new_collection_name) ...

    # 3. 原子切换 alias
    if not client.has_alias(ALIAS_NAME):
        # 首次：直接创建 alias
        client.create_alias(new_collection_name, ALIAS_NAME)
    else:
        # 已有 alias：用 alter_alias 原子切换（旧集合保留 7 天，由人工清理）
        client.alter_alias(new_collection_name, ALIAS_NAME)

    print(f"[rebuild] alias '{ALIAS_NAME}' 现在指向 '{new_collection_name}'")
    print(f"[rebuild] 旧集合（如有）保留 7 天，可在 Milvus 控制台手动删除")
```

- [ ] **Step 3：验证语法**

```bash
python -c "import ast; ast.parse(open('utils/txt_spliter/vector_main.py').read())"
```

Expected: 无输出。

- [ ] **Step 4：Commit**

```bash
git add utils/txt_spliter/vector_main.py
git commit -m "feat(milvus): replace drop+create with atomic alias swap"
```

---

## Task 2.7：添加 lifespan hook 到 main.py

**Files:**
- Modify: `main.py`

- [ ] **Step 1：在文件顶部 import 加 lifespan**

修改 `main.py` 顶部：

```python
from contextlib import asynccontextmanager
from pathlib import Path
import logging

from fastapi import FastAPI, Request
from uvicorn import run
```

- [ ] **Step 2：在 app = FastAPI() 之后、router 挂载之前添加 lifespan**

```python
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动期校验：UPLOAD_DIR 可写、Milvus 探活。"""
    upload_dir = Path("documents").resolve()
    if not upload_dir.exists():
        upload_dir.mkdir(parents=True, exist_ok=True)
        logger.warning(f"创建上传目录: {upload_dir}")
    if not upload_dir.is_dir() or not upload_dir.exists():
        raise RuntimeError(f"上传目录不可写: {upload_dir}")

    # Milvus 探活（不阻塞启动）
    try:
        from pymilvus import MilvusClient
        from utils.models.embedding_model import EmbeddingModel
        embed = EmbeddingModel.create_default()
        milvus_cfg = embed.get_milvus_config()
        client = MilvusClient(host=milvus_cfg["host"], port=milvus_cfg["port"])
        client.list_collections()
        logger.info(f"Milvus 探活成功: {milvus_cfg['host']}:{milvus_cfg['port']}")
    except Exception as e:
        logger.error(f"Milvus 探活失败（不阻塞启动）: {e}")

    yield


app = FastAPI(lifespan=lifespan)
```

（注意：`app = FastAPI()` 改为 `app = FastAPI(lifespan=lifespan)`）

- [ ] **Step 3：验证语法**

```bash
python -c "import ast; ast.parse(open('main.py').read())"
```

Expected: 无输出。

- [ ] **Step 4：Commit**

```bash
git add main.py
git commit -m "feat(main): add lifespan hook for upload dir + milvus health"
```

---

## Task 2.8：删除 web_page/knowledge_base.py 和 web_page/mcp_page.py

**Files:**
- Delete: `web_page/knowledge_base.py`, `web_page/mcp_page.py`（或 `mcp.py`）

- [ ] **Step 1：确认实际文件名**

```bash
ls web_page/
```

- [ ] **Step 2：删除文件**

```bash
git rm web_page/knowledge_base.py web_page/mcp_page.py
# 或 git rm web_page/mcp.py 看实际文件名
```

- [ ] **Step 3：Commit**

```bash
git commit -m "chore: remove unused web_page modules (knowledge_base, mcp)"
```

---

## Task 2.9：创建 web_page/repo_admin.py

**Files:**
- Create: `web_page/repo_admin.py`

- [ ] **Step 1：创建文件**

完整内容：

```python
"""web_page/repo_admin.py —— 仓库管理配置页面（R0：上传文件）。

后续扩展（不在本轮）：
- R1: 文件清单 + 删除按钮
- R2: 单文件重建
- R3: 多知识库切换
"""
import requests
import streamlit as st

API_BASE = "http://api:8000"  # docker compose 内；裸跑改 http://localhost:8000


def repo_admin_page():
    st.title("📚 仓库管理配置")
    st.caption("上传文档到知识库（R0：仅上传功能）")

    st.subheader("上传文件")
    st.markdown(
        "支持类型：**PDF / Word(.docx) / Markdown / TXT**"
    )

    uploaded = st.file_uploader(
        "选择文件",
        type=["pdf", "docx", "md", "txt"],
        accept_multiple_files=True,
    )

    if st.button("上传并解析", disabled=not uploaded):
        files = [
            ("files", (f.name, f.getvalue(), f.type))
            for f in uploaded
        ]
        try:
            r = requests.post(
                f"{API_BASE}/api/batch-upload-and-parse",
                files=files,
                params={"overwrite": False},
                timeout=300,
            )
            if r.status_code == 200:
                data = r.json()
                st.success(
                    f"完成：{len(data['upload_details']['uploaded_files'])} 个上传，"
                    f"{len(data['upload_details']['skipped_files'])} 个跳过，"
                    f"{len(data['upload_details']['failed_uploads'])} 个失败"
                )
                with st.expander("查看详情"):
                    st.json(data)
            else:
                st.error(f"上传失败：HTTP {r.status_code} - {r.text}")
        except Exception as e:
            st.error(f"请求失败：{e}")
```

- [ ] **Step 2：验证语法**

```bash
python -c "import ast; ast.parse(open('web_page/repo_admin.py').read())"
```

Expected: 无输出。

- [ ] **Step 3：Commit**

```bash
git add web_page/repo_admin.py
git commit -m "feat(web): add repo_admin page with file upload (R0)"
```

---

## Task 2.10：重写 main_web.py 为 3 页面布局

**Files:**
- Modify: `main_web.py`

- [ ] **Step 1：用以下内容覆盖文件**

完整内容：

```python
"""main_web.py —— Streamlit 入口，三页面布局。

1. Agent 智能问答（默认）—— 走 /agent/chat
2. RAG 知识库问答 —— 直连 /rag，进阶证明
3. 仓库管理配置 —— 上传文件、查看状态（R0 仅上传）
"""
import streamlit as st
import streamlit_antd_components as sac

from web_page.rag_page import rag_page
from web_page.rag_direct_page import rag_direct_page
from web_page.repo_admin import repo_admin_page

st.set_page_config(page_title="RAGMI", layout="centered")

st.markdown(
    """
    <style>
    section[data-testid="stSidebar"] {
        width: 300px !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    selected_page = sac.menu(
        [
            sac.MenuItem("智能问答", icon="chat"),
            sac.MenuItem("知识库问答", icon="book"),
            sac.MenuItem("仓库管理配置", icon="hdd-stack"),
        ],
        key="selected_page",
        open_index=0,
    )

if selected_page == "知识库问答":
    rag_direct_page()
elif selected_page == "仓库管理配置":
    repo_admin_page()
else:
    rag_page()  # Agent 智能问答（默认）
```

- [ ] **Step 2：创建 web_page/rag_direct_page.py（直连 RAG 的简单页面）**

```python
"""web_page/rag_direct_page.py —— 直连 /rag 的简单问答页面（无 Agent 编排）。"""
import requests
import streamlit as st

API_BASE = "http://api:8000"


def rag_direct_page():
    st.title("📖 知识库问答（直连 RAG）")
    st.caption("绕过 Agent，直接调 /rag 端点，证明 RAG 组件独立可用")

    if "rag_messages" not in st.session_state:
        st.session_state.rag_messages = []

    for msg in st.session_state.rag_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("问个问题（仅查知识库）"):
        st.session_state.rag_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("检索中..."):
                try:
                    r = requests.post(
                        f"{API_BASE}/rag",
                        json={"query": prompt},
                        timeout=60,
                    )
                    if r.status_code == 200:
                        answer = r.json().get("answer", "(无答案)")
                    else:
                        answer = f"HTTP {r.status_code}: {r.text}"
                except Exception as e:
                    answer = f"请求失败：{e}"
                st.markdown(answer)

        st.session_state.rag_messages.append({"role": "assistant", "content": answer})
```

- [ ] **Step 3：验证语法**

```bash
python -c "import ast; ast.parse(open('main_web.py').read())"
python -c "import ast; ast.parse(open('web_page/rag_direct_page.py').read())"
```

- [ ] **Step 4：Commit**

```bash
git add main_web.py web_page/rag_direct_page.py
git commit -m "feat(web): 3-page sidebar layout (Agent/RAG/Repo Admin)"
```

---

## Task 2.11：M2 端到端验证

- [ ] **Step 1：创建测试 fixture**

```bash
mkdir -p test/fixtures
cat > test/fixtures/sample.txt <<'EOF'
RAGMI 是一个基于 RAG + Agent 的个人知识库问答系统。
本测试文件用于验证上传→检索闭环。
关键词：ragmi_test_marker_2026。
EOF
```

- [ ] **Step 2：启动后端（裸跑或 compose）**

```bash
# 方式 A: docker compose
docker compose up -d

# 方式 B: 裸跑
python main.py &
```

- [ ] **Step 3：上传文件**

```bash
curl -X POST http://localhost:8000/api/batch-upload-and-parse \
  -F "files=@test/fixtures/sample.txt;filename=sample.txt"
```

Expected: 返回 200，包含 `uploaded_files` 至少一项。

- [ ] **Step 4：等解析完成后提问**

```bash
sleep 30
curl -X POST http://localhost:8000/agent/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "ragmi_test_marker_2026 是什么？"}'
```

Expected: 答案中包含 "ragmi_test_marker_2026" 和文件原文内容。

- [ ] **Step 5：清理**

```bash
docker compose down
# 或 kill 后台进程
rm -f documents/sample.txt
```

**M2 通过标准**：上传 → 提问 → 答案含原文。

---

# 阶段 3：M3 评估与测试可信

## Task 3.0：实测 reflection_count 行为（决策任务）

**Files:**
- Read: `agent/state.py`, `agent/nodes/reflect.py`, `agent/graph.py`

- [ ] **Step 1：写一个最小复现脚本 test_reflection_count.py**

文件内容：

```python
"""test_reflection_count.py —— 实测 reflection_count 行为，判断是否需要修复。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from langchain_core.messages import HumanMessage, AIMessage
from agent.nodes import reflect as reflect_mod
from agent.state import AgentState, MAX_REFL


class MockLLM:
    def __init__(self, content):
        self.content = content
        self.invoke_calls = []

    def invoke(self, messages):
        self.invoke_calls.append(messages)
        from langchain_core.messages import AIMessage
        return AIMessage(content=self.content)


def main():
    print(f"MAX_REFL = {MAX_REFL}")
    print(f"AgentState fields: {list(AgentState.__annotations__.keys())}")
    print()

    # 场景 1: reflection_count=0（初始）
    mock = MockLLM('{"is_sufficient": false, "critique": "需要更多信息"}')
    reflect_mod._llm = mock

    state = {
        "messages": [HumanMessage(content="q"), AIMessage(content="a")],
        "reflection_count": 0,
    }
    result = reflect_mod.reflect_node(state)
    print(f"场景 1 (count=0): reflection_count={result['reflection_count']}, pass={result['last_reflection_pass']}")
    # 期望：reflection_count 增到 1（因为 reducer +1），pass=False（因为 mock 说不够）

    # 场景 2: reflection_count=1（等于 MAX_REFL）
    state["reflection_count"] = 1
    result = reflect_mod.reflect_node(state)
    print(f"场景 2 (count=1=MAX_REFL): reflection_count={result['reflection_count']}, pass={result['last_reflection_pass']}")
    # 期望：reflection_count 应该是 1+1=2（reducer +1），但 pass 应该是 True（MAX_REFL 兜底强制 pass）


if __name__ == "__main__":
    main()
```

- [ ] **Step 2：跑脚本**

```bash
python test/test_reflection_count.py
```

记录输出到决策表：

| 场景 | 实际 reflection_count | 实际 pass | 是否符合预期 |
|------|---------------------|----------|------------|

- [ ] **Step 3：决策**

如果两行都符合预期 → 行为正确，无须改 agent/state.py，继续 M3。
如果 reflection_count 被 reducer 累加后超过 MAX_REFL 但 pass 仍 False → 需要在 reflect_node line 92 的 `current_count >= MAX_REFL` 改为 `current_count >= MAX_REFL - 1`（先减后比），并在 state.py 改 MAX_REFL 默认 0。

- [ ] **Step 4：删除临时脚本**

```bash
git rm test/test_reflection_count.py
```

- [ ] **Step 5：Commit（如有改动）**

```bash
git commit -m "fix(reflect): correct MAX_REFL boundary"  # 仅当 Step 3 决定要改
# 或
git commit --allow-empty -m "verify: reflection_count behavior is correct"
```

---

## Task 3.1：删除 test/test_agent.py

**Files:**
- Delete: `test/test_agent.py`

- [ ] **Step 1：删除文件**

```bash
git rm test/test_agent.py
```

- [ ] **Step 2：Commit**

```bash
git commit -m "test: remove dead test_agent.py (imports deleted v1 controller)"
```

---

## Task 3.2：修复 T06 测试预期

**Files:**
- Modify: `test/agent_test_cases.json`

- [ ] **Step 1：找到 T06 用例**

```bash
grep -A 3 '"id": "T06"' test/agent_test_cases.json
```

- [ ] **Step 2：修改 expected_tool 为 "chat"**

将 T06 的 `"expected_tool": "rag"` 改为 `"expected_tool": "chat"`。

并在该用例加注释字段说明原因：

```json
{
  "id": "T06",
  "query": "什么是 ReAct 模式？",
  "expected_tool": "chat",
  "note": "ReAct 是通用概念，不在知识库内，按 prompt 设计应走 chat。若日后上传 ReAct 文档，需改回 rag。"
}
```

- [ ] **Step 3：验证 JSON 语法**

```bash
python -c "import json; json.load(open('test/agent_test_cases.json'))"
```

Expected: 无输出。

- [ ] **Step 4：Commit**

```bash
git add test/agent_test_cases.json
git commit -m "test: fix T06 expectation (ReAct is general concept → chat)"
```

---

## Task 3.3：增强 run_agent_eval.py 加 status 字段 + --mock

**Files:**
- Modify: `test/run_agent_eval.py`

- [ ] **Step 1：在 imports 后、main() 前加 MockLLM 类**

修改 `test/run_agent_eval.py`，在 `def evaluate_one(...)` 之前加入：

```python
class MockLLM:
    """用于 --mock 模式的假 LLM。返回简单的 chat 响应。"""

    def __init__(self):
        self.invoke_calls = []

    def invoke(self, messages):
        self.invoke_calls.append(messages)
        from langchain_core.messages import AIMessage
        return AIMessage(content="[MOCK] 这是 mock LLM 的回答。")
```

- [ ] **Step 2：在 main() 中增加 --mock 参数解析**

修改 `def main():` 第一行后插入：

```python
    import sys
    use_mock = "--mock" in sys.argv
    if use_mock:
        # Patch agent 模块的 LLM 创建
        from agent.nodes import reflect as reflect_mod
        reflect_mod._llm = MockLLM()
```

并在 evaluate_one 函数开头加 mock 短路：

```python
def evaluate_one(graph, query: str, use_mock: bool = False) -> tuple[str, str, int, int]:
    """返回 (response, status, iterations, reflection_count)。
    status: 'correct' | 'wrong_tool' | 'exception'
    """
    if use_mock:
        from agent.runtime import ask
        debug_result = ask(query, debug=True)
        # mock 模式下默认全判为 chat（因为 mock LLM 不调工具）
        return debug_result["answer"], "correct", 0, 0

    from agent.runtime import ask
    try:
        debug_result = ask(query, debug=True)
    except Exception as e:
        return f"[EXCEPTION] {e}", "exception", 0, 0

    if isinstance(debug_result, str):
        return debug_result, "exception", 0, 0

    return debug_result["answer"], "correct", debug_result["iterations"], debug_result["reflection_count"]
```

- [ ] **Step 3：修改主循环，使用 status 字段**

修改 main() 主循环中的判断逻辑：

将原来的：
```python
            is_correct = (actual == expected)
```

改为：
```python
            if status == "exception":
                actual = "error"
                is_correct = False
            else:
                actual = "rag" if tool_called else "chat"
                is_correct = (actual == expected)
```

并将 `details.append({...})` 中加 `"status": status` 字段。

- [ ] **Step 4：在 summary 计算逻辑中按 status 分桶**

替换 summary 计算块：

```python
    correct = sum(1 for d in details if d.get("status") == "correct" and d.get("correct"))
    exceptions = sum(1 for d in details if d.get("status") == "exception")
    wrong_tool = sum(1 for d in details if d.get("status") == "correct" and not d.get("correct"))

    accuracy = correct / total * 100 if total else 0
    stability = (total - exceptions) / total * 100 if total else 0

    print(f"\n总准确率: {correct}/{total} = {accuracy:.1f}%")
    print(f"  - Tool Routing Accuracy: {correct}/{total-correct-wrong_tool} = {correct/(total-wrong_tool)*100 if (total-wrong_tool) else 0:.1f}%")
    print(f"  - Agent Stability: {total-exceptions}/{total} = {stability:.1f}%")
    print(f"  - Exceptions: {exceptions}, Wrong Tool: {wrong_tool}")
```

- [ ] **Step 5：验证语法**

```bash
python -c "import ast; ast.parse(open('test/run_agent_eval.py').read())"
```

Expected: 无输出。

- [ ] **Step 6：Commit**

```bash
git add test/run_agent_eval.py
git commit -m "test(eval): add status field + --mock flag + stability metric"
```

---

## Task 3.4：创建 pytest.ini

**Files:**
- Create: `pytest.ini`

- [ ] **Step 1：创建文件**

```ini
[pytest]
testpaths = test
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -v --tb=short
```

- [ ] **Step 2：Commit**

```bash
git add pytest.ini
git commit -m "test: add pytest.ini"
```

---

## Task 3.5：创建 Makefile

**Files:**
- Create: `Makefile`

- [ ] **Step 1：创建文件**

```makefile
.PHONY: test test-unit test-eval test-mock clean help

help:
	@echo "RAGMI 测试入口："
	@echo "  make test       - 跑单元测试 + 评估（mock 模式，不需要真实 LLM key）"
	@echo "  make test-eval  - 跑评估（需要 .env 有真实 LLM key）"
	@echo "  make test-unit  - 只跑单元测试"
	@echo "  make test-mock  - 跑评估（mock 模式）"
	@echo "  make clean      - 清理缓存"

test: test-unit test-mock

test-unit:
	pytest test/test_reflect.py -v

test-mock:
	python test/run_agent_eval.py --mock

test-eval:
	python test/run_agent_eval.py

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .coverage
```

- [ ] **Step 2：验证 make 可解析**

```bash
make help
```

Expected: 输出 help 文本。

- [ ] **Step 3：Commit**

```bash
git add Makefile
git commit -m "build: add Makefile with test targets"
```

---

## Task 3.6：M3 验证

- [ ] **Step 1：跑单元测试**

```bash
make test-unit
```

Expected: 10/10 pass。

- [ ] **Step 2：跑 mock 模式评估**

```bash
make test-mock
```

Expected: 输出 12/12 = 100% Tool Routing Accuracy，Agent Stability 100%。

- [ ] **Step 3：检查 results JSON**

```bash
cat test/agent_eval_results.json | python -m json.tool | head -20
```

Expected: summary 包含 tool routing + stability 字段。

**M3 通过标准**：`make test` 全绿。

---

# 阶段 4：M4 文档与可观测

## Task 4.1：创建 utils/logging.py

**Files:**
- Create: `utils/logging.py`

- [ ] **Step 1：创建文件**

```python
"""utils/logging.py —— 统一日志配置。

格式：时间 级别 模块 消息
例：2026-07-19 14:23:01 INFO agent.runtime ask() entry query="..."
"""
import logging
import sys


def setup_logging(level: str = "INFO"):
    """初始化项目级 logger。

    调用一次即可（在 main.py lifespan 启动时调）。
    """
    fmt = "%(asctime)s %(levelname)s %(name)s %(message)s"
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format=fmt,
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
        force=True,  # 覆盖已有的 root logger 配置
    )
    # 静默 httpx / urllib3 的 DEBUG 日志
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """便捷获取 logger。"""
    return logging.getLogger(name)
```

- [ ] **Step 2：Commit**

```bash
git add utils/logging.py
git commit -m "feat(logging): add centralized logging config"
```

---

## Task 4.2：在 main.py lifespan 中调用 setup_logging

**Files:**
- Modify: `main.py`

- [ ] **Step 1：在 lifespan 函数开头加 setup_logging**

```python
from utils.logging import setup_logging

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging("INFO")
    # ... 原有内容
```

- [ ] **Step 2：Commit**

```bash
git add main.py
git commit -m "feat(main): call setup_logging in lifespan"
```

---

## Task 4.3：替换 agent/runtime.py 的 print 为 logger

**Files:**
- Modify: `agent/runtime.py`

- [ ] **Step 1：在文件顶部加 import**

```python
from utils.logging import get_logger

logger = get_logger(__name__)
```

- [ ] **Step 2：替换 line 76 的 print**

将：
```python
        print(f"[agent error] {type(e).__name__}: {e}")
```

改为：
```python
        logger.exception(f"ask() failed: {type(e).__name__}: {e}")
```

- [ ] **Step 3：在 ask() 入口加 debug 日志**

在 `def ask(...)` 函数体最开头加：

```python
    logger.info(f"ask() entry: query={question[:50]}... session={session_id}")
```

- [ ] **Step 4：Commit**

```bash
git add agent/runtime.py
git commit -m "refactor(agent): replace print with logger in runtime"
```

---

## Task 4.4：替换 agent/nodes/agent.py 的 print（如果有）

**Files:**
- Modify: `agent/nodes/agent.py`

- [ ] **Step 1：检查是否有 print**

```bash
grep -n "print(" agent/nodes/agent.py
```

- [ ] **Step 2：如果有，按 Task 4.3 模式替换**

如果无 print，跳过此任务。

- [ ] **Step 3：Commit**

```bash
git add agent/nodes/agent.py
git commit -m "refactor(agent): replace print with logger in agent_node"
# 或 --allow-empty
```

---

## Task 4.5：替换 agent/nodes/reflect.py 的 print（如果有）

**Files:**
- Modify: `agent/nodes/reflect.py`

- [ ] **Step 1：检查是否有 print**

```bash
grep -n "print(" agent/nodes/reflect.py
```

- [ ] **Step 2：按 Task 4.3 模式替换**

- [ ] **Step 3：Commit**

```bash
git add agent/nodes/reflect.py
git commit -m "refactor(agent): replace print with logger in reflect_node"
```

---

## Task 4.6：替换 core/rags/rags.py 的 print 为 logger

**Files:**
- Modify: `core/rags/rags.py`

- [ ] **Step 1：检查 print**

```bash
grep -n "print(" core/rags/rags.py
```

- [ ] **Step 2：替换**

```python
from utils.logging import get_logger
logger = get_logger(__name__)
```

把所有 print 替换为 logger.info / logger.warning / logger.error（按语义）。

- [ ] **Step 3：Commit**

```bash
git add core/rags/rags.py
git commit -m "refactor(rag): replace print with logger"
```

---

## Task 4.7：重写 CLAUDE.md 架构章节

**Files:**
- Modify: `CLAUDE.md`（第 28-86 行：架构章节）

- [ ] **Step 1：先读全文确认行号**

```bash
grep -n "^## \|^### " CLAUDE.md
```

- [ ] **Step 2：替换"Architecture" 章节**

将整个 "Architecture" 章节（含 Layered Architecture 和 Agent Architecture 子章节）替换为：

```markdown
## Architecture (v2.1 LangGraph)

### Layered Architecture

\`\`\`
┌─────────────────────────────────────────────┐
│  Streamlit Frontend (main_web.py)           │
│  - Page 1: Agent 智能问答（默认）             │
│  - Page 2: RAG 知识库问答（直连 /rag）        │
│  - Page 3: 仓库管理配置（上传文件）            │
└─────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────┐
│  FastAPI Backend (main:app, port 8000)      │
│  - /agent/chat  - ReAct + Reflection        │
│  - /rag         - Direct RAG                │
│  - /chat        - Direct LLM                │
│  - /api/upload-and-parse - 文件上传          │
│  - /debug/simple - 后端存活探测              │
└─────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────┐
│  Agent Layer (agent/, LangGraph v2.1)       │
│  - graph.py: StateGraph (3 nodes)           │
│  - nodes/: agent / tools / reflect           │
│  - state.py: MAX_ITERS=5, MAX_REFL=1         │
│  - runtime.py: ask() 统一入口                │
└─────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────┐
│  Core Layer                                 │
│  - core/rags/rags.py: RAG pipeline           │
│  - utils/models/embedding_model.py           │
│  - utils/txt_spliter/vector_main.py          │
│    (alias swap for safe rebuild)             │
└─────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────┐
│  Data Layer                                 │
│  - Milvus (alias "langchain" → active coll)  │
│  - MessageManager: 会话历史                  │
└─────────────────────────────────────────────┘
\`\`\`

### ReAct Agent Pattern (v2.1)

\`\`\`
agent → {tools, reflect, END}
  ↓
tools → agent   (ReAct 循环)
  ↓
reflect → {agent, END}   (Self-Reflection)
\`\`\`

Tool selection：LLM 输出 JSON `{tool, confidence, reasoning}`，
\`parse_tool_choice_json()\` 解析，confidence < 0.5 fallback 到 chat。

Self-correction (v2.1)：reflect_node 用 LLM-as-judge 评答案质量，
不充分则追加 critique AIMessage 回 agent 重答，最多 MAX_REFL=1 次。
```

- [ ] **Step 3：验证 Markdown 语法**

```bash
python -c "
import re
content = open('CLAUDE.md').read()
# 简单检查：标题层级合理
assert '## Architecture' in content
assert '## Commands' in content
print('CLAUDE.md OK')
"
```

- [ ] **Step 4：Commit**

```bash
git add CLAUDE.md
git commit -m "docs: rewrite CLAUDE.md architecture section for v2.1 LangGraph"
```

---

## Task 4.8：补充 README.md Docker + 测试章节

**Files:**
- Modify: `README.md`

- [ ] **Step 1：在 README.md 顶部 ## Installation 之前插入 ## Quick Start**

```markdown
## Quick Start (Docker)

\`\`\`bash
# 1. 复制环境变量模板
cp .env.example .env
# 编辑 .env，填入 MINIMAX_API_KEY（必需）

# 2. 启动全部服务
docker compose up -d

# 3. 验证
curl http://localhost:8000/debug/simple
# 浏览器访问 http://localhost:8501

# 4. 关闭
docker compose down
\`\`\`

## Quick Start (Manual)

\`\`\`bash
# 后端
pip install -r requirements.txt
python main.py

# 前端（新终端）
pip install streamlit streamlit-antd-components
streamlit run main_web.py
\`\`\`

## Running Tests

\`\`\`bash
# 单元测试 + mock 评估（不需要真实 LLM key）
make test

# 或分别跑
make test-unit      # pytest test_reflect.py
make test-mock      # 12 个 agent 用例，mock LLM
make test-eval      # 真实 LLM 评估（需要 .env）
\`\`\`
```

- [ ] **Step 2：Commit**

```bash
git add README.md
git commit -m "docs: add Quick Start + Running Tests sections to README"
```

---

## Task 4.9：归档 docs/STATUS.md

**Files:**
- Move: `docs/STATUS.md` → `docs/archive/2026-07-08-pre-v2.1.md`

- [ ] **Step 1：创建 archive 目录**

```bash
mkdir -p docs/archive
```

- [ ] **Step 2：移动并加顶部注释**

```bash
git mv docs/STATUS.md docs/archive/2026-07-08-pre-v2.1.md
```

在文件顶部加注释：

```markdown
> ⚠️ **本文件已冻结（2026-07-08），仅供考古**
>
> 当前项目状态以 `CLAUDE.md` 为准。本快照记录的是 v1 → v2 演进前的状态。
> 详细修复路线见 `docs/superpowers/specs/2026-07-19-repair-closeout-design.md`。

---

（原内容）
```

- [ ] **Step 3：Commit**

```bash
git add docs/STATUS.md docs/archive/2026-07-08-pre-v2.1.md
git commit -m "docs: archive pre-v2.1 STATUS.md (frozen 2026-07-08)"
```

---

## Task 4.10：M4 验证

- [ ] **Step 1：验证 CLAUDE.md 中提到的文件路径都存在**

```bash
python -c "
import re
import os
content = open('CLAUDE.md').read()
paths = re.findall(r'\`(agent/[a-z_/]+\.py|core/[a-z_/]+\.py|utils/[a-z_/]+\.py|api/[a-z_/]+\.py|main\.py|main_web\.py)\`', content)
missing = [p for p in paths if not os.path.exists(p)]
if missing:
    print('MISSING:', missing)
    exit(1)
print(f'{len(paths)} paths OK')
"
```

Expected: `N paths OK`，无 MISSING。

- [ ] **Step 2：跑完整测试**

```bash
make test
```

Expected: 全绿。

- [ ] **Step 3：启动后端验证日志输出**

```bash
python main.py &
sleep 5
curl http://localhost:8000/debug/simple
# 应该看到 lifespan 的 INFO 日志："Milvus 探活成功..." 或失败 ERROR
kill %1
```

**M4 通过标准**：所有路径校验通过、测试全绿、日志正常输出。

---

# 总验收（4 阶段全部完成后）

- [ ] **Step 1：清理环境**

```bash
docker compose down -v
rm -rf .pytest_cache .coverage
```

- [ ] **Step 2：从零启动验证**

```bash
docker compose up -d
sleep 30
curl http://localhost:8000/debug/simple       # 200
curl -F "files=@test/fixtures/sample.txt" http://localhost:8000/api/batch-upload-and-parse  # 200
sleep 20
curl -X POST http://localhost:8000/agent/chat -H "Content-Type: application/json" -d '{"query":"ragmi_test_marker_2026 是什么？"}'  # 答案含原文
```

- [ ] **Step 3：跑测试**

```bash
make test  # 全绿
```

- [ ] **Step 4：检查文档一致性**

```bash
# CLAUDE.md 引用的所有路径都存在
python -c "..."  # 见 Task 4.10 Step 1
```

**最终通过标准**：以上 4 步全过。

---

# 风险与回滚

## 每个 Task 失败回滚

由于每个 Task 后都有 commit，回滚只需：

```bash
git log --oneline -20   # 找到上一个好的 commit
git reset --hard <good_commit_hash>
```

## 整体回滚

```bash
git log --oneline -- docs/superpowers/specs/2026-07-19-repair-closeout-design.md
git revert --no-commit <all_commits_since_spec>
```

## 不破坏现状的保证

- 每个 Task 的 commit 是独立单元
- 失败的 Task 在下一个 Task 开始前可被 revert
- docker compose down -v 完全清理
- 测试在每个 M 阶段结束后跑，确保不破坏现有功能

---

# 后续（不在本轮范围）

详见 spec "后续" 章节：
- R1-R5 仓库管理配置演进
- M5: 真实 LangSmith 评估
- M6: MCP 工具接入
- M7: BM25 混合检索
- M8: GitHub Actions CI
- M9: alias 清理定时任务