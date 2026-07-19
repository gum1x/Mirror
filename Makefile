PY ?= python3
ME ?= Sam
IN ?= data/raw

.PHONY: help test lint fmt status clean pipeline install

help:
	@echo "Mirror — common tasks:"
	@echo "  make test       Run the regression test suite (stdlib, no install)"
	@echo "  make lint       Lint scripts + tests with ruff"
	@echo "  make fmt        Format with ruff"
	@echo "  make status     Show build progress for the current dir"
	@echo "  make install    Install the cloud-path extras (Claude + OpenAI + RAG)"
	@echo "  make clean      Dry-run remove local artifacts (ARGS=--yes to delete)"
	@echo "  make pipeline   normalize -> scrub -> persona -> build  (IN=dir ME=name)"

test:
	$(PY) tests/test_pipeline.py
	$(PY) tests/test_connectors.py

lint:
	@command -v ruff >/dev/null 2>&1 || { echo "install ruff:  pipx install ruff"; exit 1; }
	ruff check scripts tests

fmt:
	ruff format scripts tests

status:
	$(PY) scripts/status.py

install:
	pip install ".[cloud]"

clean:
	$(PY) scripts/maintenance/purge.py $(ARGS)

# End-to-end on a folder of unified JSONL:  make pipeline IN=data/raw ME="Sam Rivera"
pipeline:
	$(PY) scripts/format/normalize.py $(IN)/*.jsonl --dedup -o data/clean.jsonl
	$(PY) scripts/format/pii_scrub.py data/clean.jsonl -o data/scrubbed.jsonl
	$(PY) scripts/persona/style_analyze.py data/scrubbed.jsonl --name "$(ME)" -o persona/
	$(PY) scripts/format/build_dataset.py data/scrubbed.jsonl --format openai-chat \
	    --system-file persona/style_card.md --holdout 0.1 -o data/train.jsonl
