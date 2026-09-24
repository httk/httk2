PYTHON ?= python3
DIST_DIR ?= dist

# Module-workspace helpers: check out and operate on the repositories under
# $(MODULES_DIR). The default modules are cloned by "make checkout" when absent
# and are listed in dependency order. Any other repository found there is
# picked up automatically: one carrying the httk-module-template release
# infrastructure (tools/check_release.py) is a release module, released from
# develop by the coordinated targets; anything else is a development repository
# that only pull, fetch, and push touch, on its current branch.
MODULES_DIR ?= modules
HTTK_GIT_BASE ?= git@github.com:httk
HTTK_DEFAULT_MODULES ?= httk-core httk-store httk-atomistic httk-analyse httk-serve httk-workflow
HTTK_DOCS_REPOSITORY ?= httk.github.io
HTTK_CHECKED_OUT := $(notdir $(patsubst %/.git,%,$(wildcard $(MODULES_DIR)/*/.git)))
HTTK_MODULES ?= $(HTTK_DEFAULT_MODULES) $(sort $(foreach r,\
	$(filter-out $(HTTK_DEFAULT_MODULES) $(HTTK_DOCS_REPOSITORY),$(HTTK_CHECKED_OUT)),\
	$(if $(wildcard $(MODULES_DIR)/$(r)/tools/check_release.py),$(r))))
HTTK_DEV_REPOSITORIES ?= $(filter-out $(HTTK_MODULES) $(HTTK_DOCS_REPOSITORY),$(HTTK_CHECKED_OUT))
HTTK_REPOSITORIES ?= $(HTTK_MODULES) $(HTTK_DOCS_REPOSITORY) $(HTTK_DEV_REPOSITORIES)
HTTK_MANAGED_REFS = $(foreach r,$(HTTK_MODULES),$(MODULES_DIR)/$(r):develop) \
	$(MODULES_DIR)/$(HTTK_DOCS_REPOSITORY):main
GIT_USER_NAME ?= Rickard Armiento
GIT_USER_EMAIL ?= rickard-gpg@armiento.net
READ_PROJECT_VERSION = $(PYTHON) -c 'import sys, tomllib; print(tomllib.load(sys.stdin.buffer)["project"]["version"])'
READ_PROJECT_EXTRAS = $(PYTHON) -c 'import sys, tomllib; print(",".join(tomllib.load(sys.stdin.buffer)["project"].get("optional-dependencies", ())))'
RELEASE_STATE ?= .release-batch.json
DOCS_BASE_URL ?= https://docs.httk.org
RELEASE_BATCH = $(PYTHON) -m tools.release --state "$(RELEASE_STATE)"

# Run "git $(1)" in every checked-out repository; report missing checkouts and
# fail at the end if anything failed.
define git_foreach
	@fail=0; for r in $(HTTK_REPOSITORIES); do \
	  if [ -d "$(MODULES_DIR)/$$r/.git" ]; then \
	    echo "== $$r ($$(git -C "$(MODULES_DIR)/$$r" branch --show-current))"; \
	    git -C "$(MODULES_DIR)/$$r" $(1) || fail=1; \
	  else \
	    echo "== $$r: not checked out (run 'make checkout')"; fail=1; \
	  fi; \
	done; exit $$fail
endef

.PHONY: clean dist-clean dist dist-check release-check release-prepare checkout fetch pull push \
	install ci release-check-all release-docs-build release-aggregate-docs-build release-merge-tag-and-push-main

checkout:
	@mkdir -p $(MODULES_DIR)
	@for spec in $(HTTK_MANAGED_REFS); do \
	  repo=$${spec%:*}; branch=$${spec#*:}; name=$$(basename "$$repo"); \
	  if [ -d "$$repo/.git" ]; then \
	    echo "== $$name: switching to $$branch"; \
	    if git -C "$$repo" show-ref --verify --quiet "refs/heads/$$branch"; then \
	      git -C "$$repo" switch "$$branch" || exit 1; \
	    else \
	      git -C "$$repo" fetch origin "$$branch" || exit 1; \
	      git -C "$$repo" switch --track -c "$$branch" "origin/$$branch" || exit 1; \
	    fi; \
	  else \
	    echo "== $$name: cloning $$branch"; \
	    git clone --branch "$$branch" "$(HTTK_GIT_BASE)/$$name.git" "$$repo" || exit 1; \
	  fi; \
	done
	@for r in $(HTTK_DEV_REPOSITORIES); do \
	  echo "== $$r: development repository on $$(git -C "$(MODULES_DIR)/$$r" branch --show-current) (no release infrastructure)"; \
	done

fetch:
	$(call git_foreach,fetch)

pull: checkout
	@if git show-ref --verify --quiet refs/heads/main; then \
	  git switch main; \
	else \
	  git fetch origin main; \
	  git switch --track -c main origin/main; \
	fi
	@git pull --ff-only origin main
	@for spec in $(HTTK_MANAGED_REFS); do \
	  repo=$${spec%:*}; branch=$${spec#*:}; \
	  git -C "$$repo" fetch origin main --tags || exit 1; \
	  git -C "$$repo" pull --ff-only origin "$$branch" || exit 1; \
	done
	@for r in $(HTTK_DEV_REPOSITORIES); do \
	  git -C "$(MODULES_DIR)/$$r" pull --ff-only || exit 1; \
	done
	@git -C "$(MODULES_DIR)/$(HTTK_DOCS_REPOSITORY)" submodule sync --recursive
	@git -C "$(MODULES_DIR)/$(HTTK_DOCS_REPOSITORY)" submodule update --init --recursive

push:
	@git push
	$(call git_foreach,push)

install:
	@test -n "$$VIRTUAL_ENV" || { \
	  echo "error: no activated virtual environment (VIRTUAL_ENV is unset)"; exit 1; }
	@set -eu; set --; \
	for repo in $(foreach r,$(HTTK_REPOSITORIES),$(MODULES_DIR)/$(r)) .; do \
	  test -e "$$repo/.git" || { \
	    echo "== $$repo: not checked out (run 'make checkout')"; exit 1; }; \
	  test -f "$$repo/pyproject.toml" || { echo "== $$repo: no pyproject.toml; skipped"; continue; }; \
	  extras="$$($(READ_PROJECT_EXTRAS) < "$$repo/pyproject.toml")"; \
	  requirement="$$repo"; \
	  test -z "$$extras" || requirement="$$repo[$$extras]"; \
	  echo "== installing $$repo (editable, extras: $${extras:-none})"; \
	  set -- "$$@" --editable "$$requirement"; \
	done; \
	$(PYTHON) -m pip install "$$@"

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

release-prepare:
	@version="$$($(READ_PROJECT_VERSION) < pyproject.toml)"; \
	  test "$(VERSION)" = "v$$version" || { \
	    echo "error: VERSION=$(VERSION) does not match v$$version"; exit 1; }
	@$(MAKE) release-check

# The batch matrix deliberately excludes documentation. Later commands reuse
# the recorded exact commits and reject changes outside documentation.
ci:
	$(PYTHON) -m unittest discover -s tools -p 'test_*.py'

release-check-all:
	$(RELEASE_BATCH) check --modules-dir "$(MODULES_DIR)" --modules $(HTTK_MODULES)

release-docs-build:
	$(RELEASE_BATCH) docs --base-url "$(DOCS_BASE_URL)"

release-aggregate-docs-build:
	$(RELEASE_BATCH) aggregate-docs --site "$(MODULES_DIR)/$(HTTK_DOCS_REPOSITORY)" --base-url "$(DOCS_BASE_URL)"

release-merge-tag-and-push-main:
	$(RELEASE_BATCH) publish --user-name "$(GIT_USER_NAME)" --user-email "$(GIT_USER_EMAIL)"

status:
	ls modules | xargs -i bash -c "echo -e \"\n\n== {}\"; git -C modules/{} status"
