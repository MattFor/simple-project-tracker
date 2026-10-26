PYTHON ?= python3

.PHONY: help install dev format lint types test check clean build man release

help:
	@echo "install  install tracker into the current environment"
	@echo "dev      install the development tooling as well"
	@echo "format   run ruff format"
	@echo "lint     run ruff check"
	@echo "types    run basedpyright"
	@echo "test     run the test suite, with and without pytest"
	@echo "check    format --check, lint, types and test, what CI runs"
	@echo "build    build the sdist and the wheel"
	@echo "man      render the man page"
	@echo "clean    remove build artefacts and caches"
	@echo "release  make release V=x.y.z: version, changelog, commit, tag, push"

install:
	$(PYTHON) -m pip install -e .

dev: install
	$(PYTHON) -m pip install ruff basedpyright pytest build twine

format:
	ruff format .

lint:
	ruff check .

types:
	basedpyright

test:
	$(PYTHON) -m pytest
	$(PYTHON) tests/run.py

check:
	ruff format --check .
	ruff check .
	basedpyright
	$(PYTHON) -m pytest
	$(PYTHON) tests/run.py

build:
	$(PYTHON) -m build
	$(PYTHON) -m twine check dist/*

man:
	mandoc -T lint -W warning man/tracker.1
	mandoc -T ascii man/tracker.1 | less -R

clean:
	rm -rf build dist *.egg-info .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

release:
	@test -n "$(V)" || { echo "usage: make release V=x.y.z"; exit 1; }
	@test -z "$$(git status --porcelain)" || { echo "commit or stash your changes first"; exit 1; }
	@grep -q '^## \[Unreleased\]' CHANGELOG.md || { echo "CHANGELOG.md needs a ## [Unreleased] section"; exit 1; }
	sed -i 's/^version = ".*"/version = "$(V)"/' pyproject.toml
	sed -i 's/^## \[Unreleased\]/## [$(V)]/' CHANGELOG.md
	git commit -qam "v$(V)"
	git tag -a "v$(V)" -m "v$(V)"
	git push origin HEAD "v$(V)"
