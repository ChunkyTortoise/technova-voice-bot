.PHONY: test lint quickstart-client

test:
	pytest tests/ -v

lint:
	ruff check app tests

quickstart-client:
	@echo "Quickstart checklist for TechNova Voice Bot"
	@echo "1) cp .env.example .env"
	@echo "2) Set DEEPGRAM_API_KEY and ANTHROPIC_API_KEY"
	@echo "3) docker compose up"
	@echo "4) POST /api/reports/generate to create executive artifact"
