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