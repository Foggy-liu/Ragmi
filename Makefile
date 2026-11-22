.PHONY: test test-unit test-eval test-mock test-v22 test-v22-unit test-v22-mock test-fast test-e2e test-slow clean help

help:
	@echo "RAGMI 测试入口（4 层测试体系，详见 docs/status/测试体系.md）："
	@echo "  make test          - 跑快回归（默认，秒级）"
	@echo "  make test-fast     - 快回归：pytest -m \"not slow and not e2e\""
	@echo "  make test-e2e      - 浏览器层：pytest -m e2e（需 Playwright + Chromium）"
	@echo "  make test-slow     - 真环境：pytest -m slow（真 MiniMax + 真 Milvus，慢且花钱）"
	@echo "  make test-v22-unit - 全量：pytest -v（含上面三层 + 25 分钟的向量切分）"
	@echo "  make test-eval     - 离线工具路由评估（12 case，真 LLM，要花钱）"
	@echo "  make test-unit     - 已废弃，请用 make test-fast"
	@echo "  make test-mock     - 已废弃，请用 make test-v22-mock"
	@echo "  make test-v22      - 同 make test-v22-unit"
	@echo "  make test-v22-mock - 离线评估的 --mock 模式（reflect 用假 LLM，agent 仍真）"
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

# 离线工具路由评估（12 case）。这是 test/ 下唯一活着的离线评估脚本，
# 2026-11-18 修好了四处失效。两种模式都要真实 MiniMax key，都花钱。
# 详见 test/eval/README.md。
test-v22-mock:
	PYTHONIOENCODING=utf-8 python test/eval/run_agent_eval.py --mock

test-eval:
	PYTHONIOENCODING=utf-8 python test/eval/run_agent_eval.py

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .coverage
