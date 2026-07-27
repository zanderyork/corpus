PY := ./.venv/bin/python

.PHONY: help setup index rebuild add promote serve sync clean

help:
	@echo "Corpus engine — common tasks:"
	@echo "  make setup            Create venv, install deps, build the index"
	@echo "  make add              Process inbox/ into local/ and re-index"
	@echo "  make index            Incrementally re-index changed docs"
	@echo "  make rebuild          Wipe and rebuild the whole index"
	@echo "  make promote name=X   Promote local/X.md to canonical corpus/"
	@echo "  make sync             git pull, then re-index (team / git-as-truth mode)"
	@echo "  make clean            Remove the generated index"

setup:
	./setup.sh

index:
	$(PY) ingest.py

add: index   ## ingest also processes the inbox

rebuild:
	$(PY) ingest.py --rebuild

promote:
	@test -n "$(name)" || (echo "usage: make promote name=<doc>"; exit 1)
	$(PY) tools/promote.py $(name)

sync:
	git pull --ff-only
	$(PY) ingest.py

clean:
	rm -rf index/*.db
