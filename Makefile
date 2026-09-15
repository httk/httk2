PYTHON ?= python3
DIST_DIR ?= dist

# Module-workspace helpers: check out and operate on all httk₂ module
# repositories under $(MODULES_DIR). The list is in dependency order, which
# `install` relies on so each editable install finds its httk dependencies
# already present in the venv.
MODULES_DIR ?= modules
HTTK_GIT_BASE ?= git@github.com:httk
HTTK_MODULES ?= httk-core httk-store httk-atomistic httk-analyse httk-serve httk-workflow
READ_PROJECT_VERSION = $(PYTHON) -c 'import sys, tomllib; print(tomllib.load(sys.stdin.buffer)["project"]["version"])'

# Run "git $(1)" in every checked-out module repository (on whatever branch
# each is on); report missing checkouts and fail at the end if anything failed.
define git_foreach
	@fail=0; for r in $(HTTK_MODULES); do \
	  if [ -d "$(MODULES_DIR)/$$r/.git" ]; then \
	    echo "== $$r ($$(git -C "$(MODULES_DIR)/$$r" branch --show-current))"; \
	    git -C "$(MODULES_DIR)/$$r" $(1) || fail=1; \
	  else \
	    echo "== $$r: not checked out (run 'make checkout')"; fail=1; \
	  fi; \
	done; exit $$fail
endef

.PHONY: clean dist-clean dist dist-check release-check checkout fetch pull push install \
	release-prepare-all release-merge-tag-and-push-main

checkout:
	@mkdir -p $(MODULES_DIR)
	@for r in $(HTTK_MODULES); do \
	  if [ -d "$(MODULES_DIR)/$$r/.git" ]; then \
	    echo "== $$r: switching to develop"; \
	    if git -C "$(MODULES_DIR)/$$r" show-ref --verify --quiet refs/heads/develop; then \
	      git -C "$(MODULES_DIR)/$$r" switch develop || exit 1; \
	    else \
	      git -C "$(MODULES_DIR)/$$r" fetch origin develop || exit 1; \
	      git -C "$(MODULES_DIR)/$$r" switch --track -c develop origin/develop || exit 1; \
	    fi; \
	  else \
	    echo "== $$r: cloning develop"; \
	    git clone --branch develop "$(HTTK_GIT_BASE)/$$r.git" "$(MODULES_DIR)/$$r" || exit 1; \
	  fi; \
	done

fetch:
	$(call git_foreach,fetch)

pull: checkout
	$(call git_foreach,pull --ff-only origin develop)

push:
	$(call git_foreach,push)

install:
	@test -n "$$VIRTUAL_ENV" || { \
	  echo "error: no activated virtual environment (VIRTUAL_ENV is unset)"; exit 1; }
	@for r in $(HTTK_MODULES); do \
	  test -d "$(MODULES_DIR)/$$r/.git" || { \
	    echo "== $$r: not checked out (run 'make checkout')"; exit 1; }; \
	done
	@for r in $(HTTK_MODULES); do \
	  echo "== installing $$r (editable, with its default extra)"; \
	  $(PYTHON) -m pip install --editable "$(MODULES_DIR)/$$r[default]" || exit 1; \
	done

dist-clean:
	rm -rf build $(DIST_DIR) *.egg-info

clean: dist-clean
	find . -name "*.pyc" -print0 | xargs -0 rm -f
	find . -name "*~" -print0 | xargs -0 rm -f
	find . -name "__pycache__" -print0 | xargs -0 rm -rf

dist: dist-clean
	$(PYTHON) -m build --outdir $(DIST_DIR)

dist-check: dist
	$(PYTHON) -m twine check --strict $(DIST_DIR)/*

# The metapackage ships no code or docs, so there is nothing to check beyond the
# built distribution metadata.
release-check: dist-check

release-prepare-all:
	@for r in $(HTTK_MODULES); do \
	  test -d "$(MODULES_DIR)/$$r/.git" || { \
	    echo "== $$r: not checked out (run 'make pull')"; exit 1; }; \
	  test "$$(git -C "$(MODULES_DIR)/$$r" branch --show-current)" = develop || { \
	    echo "== $$r: develop is not checked out (run 'make pull')"; exit 1; }; \
	done
	@for r in $(HTTK_MODULES); do \
	  repo="$(MODULES_DIR)/$$r"; \
	  version="$$($(READ_PROJECT_VERSION) < "$$repo/pyproject.toml")" || exit 1; \
	  echo "== $$r: preparing v$$version"; \
	  $(MAKE) -C "$$repo" release-prepare VERSION="v$$version" || exit 1; \
	  test -z "$$(git -C "$$repo" status --porcelain)" || { \
	    echo "== $$r: release preparation updated files; commit and push them, then rerun"; exit 1; }; \
	done

# This operates on refs rather than checking out main. Each repository push is
# atomic, so its main branch and release tag are published together.
release-merge-tag-and-push-main:
	@set -eu; for r in $(HTTK_MODULES); do \
	  repo="$(MODULES_DIR)/$$r"; \
	  test -d "$$repo/.git" || { echo "== $$r: not checked out (run 'make pull')"; exit 1; }; \
	  echo "== $$r: fetching release refs"; \
	  git -C "$$repo" fetch origin main develop --tags; \
	  test "$$(git -C "$$repo" rev-parse develop)" = "$$(git -C "$$repo" rev-parse origin/develop)" || { \
	    echo "== $$r: local develop does not match origin/develop (run 'make pull')"; exit 1; }; \
	  git -C "$$repo" merge-base --is-ancestor origin/main develop || { \
	    echo "== $$r: develop cannot be fast-forwarded onto main"; exit 1; }; \
	  version="$$(git -C "$$repo" show develop:pyproject.toml | $(READ_PROJECT_VERSION))"; \
	  tag="v$$version"; \
	  ! git -C "$$repo" show-ref --verify --quiet "refs/tags/$$tag" || { \
	    echo "== $$r: tag $$tag already exists"; exit 1; }; \
	done
	@set -eu; for r in $(HTTK_MODULES); do \
	  repo="$(MODULES_DIR)/$$r"; \
	  version="$$(git -C "$$repo" show develop:pyproject.toml | $(READ_PROJECT_VERSION))"; \
	  tag="v$$version"; \
	  echo "== $$r: signing and pushing $$tag"; \
	  git -C "$$repo" tag -s -m "$$tag" "$$tag" develop; \
	  git -C "$$repo" push --atomic origin develop:develop develop:main "refs/tags/$$tag" || { \
	    git -C "$$repo" tag -d "$$tag"; exit 1; }; \
	done
