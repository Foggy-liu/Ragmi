.PHONY: test test-unit test-eval test-mock test-v22 test-v22-unit test-v22-mock test-fast test-e2e test-slow clean help

help:
	@echo "RAGMI 测试入口（4 层测试体系，详见 docs/status/测试体系.md）："
	@echo "  make test          - 跑快回归（默认，秒级）"
	@echo "  make test-fast     - 快回归：pytest -m \"not slow and not e2e\""
	@echo "  make test-e2e      - 浏览器层：pytest -m e2e（需 Playwright + Chromium）"
	@echo "  make test-slow     - 真环境：pytest -m slow（真 MiniMax + 真 Milvus，慢且花钱）"
	@echo "  make test-v22-unit - 全量：pytest -v（含上面三层 + 25 分钟的向量切分）"
	@echo "  make test-eval     - 已归档，见 test/archive/scripts/（旧 v2.1 评估脚本）"
	@echo "  make test-unit     - 已废弃，请用 make test-fast"
	@echo "  make test-mock     - 已废弃，请用 make test-v22-mock"
	@echo "  make test-v22      - 同 make test-v22-unit"
	@echo "  make test-v22-mock - 已归档，见 test/archive/scripts/（旧 v2.1 mock 评估）"
	@echo "  make clean         - 清理缓存"

test: test-fast

test-unit:
	@echo "v2.1 单元测试已废弃，请用 make test-fast"

test-mock:
	@echo "v2.1 mock 评估已废弃，请用 make test-v22-mock"

test-v22: test-v22-unit

# 全量：4 层测试体系 + 25 分钟的向量切分（test_vector_split.py）
test-v22-unit:
	pytest -v

# 快回归：跳过 slow（需真实 Milvus/Ollama/MiniMax）与 e2e（浏览器）
test-fast:
	pytest -m "not slow and not e2e" -v

# 浏览器层：进程外假后端 + 专用 Streamlit（8511）
test-e2e:
	pytest -m e2e -v --tracing=retain-on-failure

# 真环境冒烟：真 MiniMax + 真 Milvus（慢且花钱）
test-slow:
	pytest -m slow -v

# 旧的 v2.1 评估脚本已归档到 test/archive/scripts/。
# 注意：不是"完全跑不动" —— 真实 LLM 模式能跑通（需 PYTHONPATH 指向仓库根），
# 只有 --mock 分支 ImportError；详见 test/archive/README.md。
test-v22-mock:
	@echo "已归档到 test/archive/scripts/run_agent_eval.py（真实 LLM 模式仍可跑，见 test/archive/README.md）"

test-eval:
	@echo "已归档到 test/archive/scripts/run_agent_eval.py（真实 LLM 模式仍可跑，见 test/archive/README.md）"

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .coverage
