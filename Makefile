.PHONY: test test-unit test-eval test-mock test-v22 test-v22-unit test-v22-mock clean help

help:
	@echo "RAGMI 测试入口："
	@echo "  make test          - 跑 v2.2 单元测试 + 评估（mock 模式）"
	@echo "  make test-eval     - 跑 v2.2 评估（需要 .env 有真实 LLM key）"
	@echo "  make test-unit     - 已废弃，请用 make test-v22-unit"
	@echo "  make test-mock     - 已废弃，请用 make test-v22-mock"
	@echo "  make test-v22      - 跑 v2.2 单元测试 + mock 评估"
	@echo "  make test-v22-unit - 只跑 v2.2 单元测试"
	@echo "  make test-v22-mock - 只跑 v2.2 mock 评估"
	@echo "  make clean         - 清理缓存"

test: test-v22

test-unit:
	@echo "v2.1 单元测试已废弃，请用 make test-v22-unit"

test-mock:
	@echo "v2.1 mock 评估已废弃，请用 make test-v22-mock"

test-v22: test-v22-unit test-v22-mock

test-v22-unit:
	pytest test/test_v22_*.py -v --ignore=test/test_v22_eval_smoke.py

test-v22-mock:
	PYTHONIOENCODING=utf-8 PYTHONPATH=. python test/run_agent_eval.py --mock

test-eval:
	PYTHONIOENCODING=utf-8 PYTHONPATH=. python test/run_agent_eval.py

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .coverage
