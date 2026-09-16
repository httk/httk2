PYTHON ?= python3
DIST_DIR ?= dist

# Module-workspace helpers: check out and operate on all httk₂ module
# repositories under $(MODULES_DIR). The module list is in dependency order for
# coordinated release operations.
MODULES_DIR ?= modules
HTTK_GIT_BASE ?= git@github.com:httk
HTTK_MODULES ?= httk-core httk-store httk-atomistic httk-analyse httk-serve httk-workflow
HTTK_DOCS_REPOSITORY ?= httk.github.io
HTTK_REPOSITORIES ?= $(HTTK_MODULES) $(HTTK_DOCS_REPOSITORY)
HTTK_MANAGED_REFS = $(foreach r,$(HTTK_MODULES),$(MODULES_DIR)/$(r):develop) \
	$(MODULES_DIR)/$(HTTK_DOCS_REPOSITORY):main
HTTK_RELEASE_REFS = $(HTTK_MANAGED_REFS) .:main
GIT_USER_NAME ?= Rickard Armiento
GIT_USER_EMAIL ?= rickard-gpg@armiento.net
READ_PROJECT_VERSION = $(PYTHON) -c 'import sys, tomllib; print(tomllib.load(sys.stdin.buffer)["project"]["version"])'
READ_PROJECT_EXTRAS = $(PYTHON) -c 'import sys, tomllib; print(",".join(tomllib.load(sys.stdin.buffer)["project"].get("optional-dependencies", ())))'

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
	install release-check-all release-prepare-all release-merge-tag-and-push-main

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
	  git -C "$$repo" pull --ff-only origin "$$branch" || exit 1; \
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
	  test -f "$$repo/pyproject.toml" || { \
	    echo "== $$repo: not checked out (run 'make checkout')"; exit 1; }; \
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

release-prepare-all:
	@for spec in $(HTTK_RELEASE_REFS); do \
	  repo=$${spec%:*}; branch=$${spec#*:}; \
	  test -d "$$repo/.git" || { echo "== $$repo: not checked out (run 'make pull')"; exit 1; }; \
	  test "$$(git -C "$$repo" branch --show-current)" = "$$branch" || { \
	    echo "== $$repo: $$branch is not checked out (run 'make pull')"; exit 1; }; \
	  test -z "$$(git -C "$$repo" status --porcelain)" || { \
	    echo "== $$repo: worktree is not clean"; exit 1; }; \
	done
	@changed=0; for r in $(HTTK_MODULES); do \
	  repo="$(MODULES_DIR)/$$r"; \
	  version="$$($(READ_PROJECT_VERSION) < "$$repo/pyproject.toml")" || exit 1; \
	  tag="v$$version"; \
	  if git -C "$$repo" show-ref --verify --quiet "refs/tags/$$tag"; then \
	    echo "== $$r: reusing existing $$tag"; \
	  else \
	    echo "== $$r: refreshing release inputs for $$tag"; \
	    $(MAKE) -C "$$repo" docs-lock docs-inventories || exit 1; \
	    if test -n "$$(git -C "$$repo" status --porcelain)"; then \
	      echo "== $$r: release inputs updated"; changed=1; \
	    fi; \
	  fi; \
	done; \
	test $$changed = 0 || { \
	  echo "== Commit and sign the updated release inputs, then rerun make release-prepare-all"; exit 1; }
	@set -eu; \
	  site="$(MODULES_DIR)/$(HTTK_DOCS_REPOSITORY)"; \
	  temporary_tags=""; \
	  cleanup_tags() { \
	    for item in $$temporary_tags; do \
	      nested=$${item%%:*}; tag=$${item#*:}; \
	      git -C "$$nested" tag -d "$$tag" >/dev/null 2>&1 || true; \
	    done; \
	  }; \
	  trap cleanup_tags EXIT HUP INT TERM; \
	  for r in $(HTTK_MODULES); do \
	    source="$$(cd "$(MODULES_DIR)/$$r" && pwd)"; \
	    nested="$$site/submodules/$$r"; \
	    test -e "$$nested/.git" || { \
	      echo "== $(HTTK_DOCS_REPOSITORY): $$r is not initialized (run 'make pull')"; exit 1; }; \
	    version="$$($(READ_PROJECT_VERSION) < "$$source/pyproject.toml")"; \
	    tag="v$$version"; \
	    if git -C "$$source" show-ref --verify --quiet "refs/tags/$$tag"; then \
	      commit="$$(git -C "$$source" rev-parse "$$tag^{}")"; \
	    else \
	      commit="$$(git -C "$$source" rev-parse develop)"; \
	    fi; \
	    git -C "$$nested" fetch "$$source" develop --tags; \
	    git -C "$$nested" checkout --detach "$$commit"; \
	    if git -C "$$nested" show-ref --verify --quiet "refs/tags/$$tag"; then \
	      test "$$(git -C "$$nested" rev-parse "$$tag^{}")" = "$$commit" || { \
	        echo "== $$r: $$tag does not identify develop"; exit 1; }; \
	    else \
	      git -C "$$nested" -c tag.gpgSign=false tag "$$tag" "$$commit"; \
	      temporary_tags="$$temporary_tags $$nested:$$tag"; \
	    fi; \
	    git -C "$$site" add "submodules/$$r"; \
	  done; \
	  version="$$($(READ_PROJECT_VERSION) < "$$site/pyproject.toml")"; \
	  $(MAKE) -C "$$site" ecosystem-manifest-release docs-lock; \
	  git -C "$$site" add docs/ecosystem.json docs/requirements.lock; \
	  if ! git -C "$$site" diff --cached --quiet; then \
	    git -C "$$site" -c user.name="$(GIT_USER_NAME)" -c user.email="$(GIT_USER_EMAIL)" \
	      commit -m "Prepare v$$version documentation snapshot"; \
	  fi; \
	  test -z "$$(git -C "$$site" status --porcelain)" || { \
	    echo "== $(HTTK_DOCS_REPOSITORY): release preparation left uncommitted changes"; exit 1; }
	@echo "== Preparation complete; sign generated commits, run make push, then make release-check-all"

release-check-all:
	@for spec in $(HTTK_RELEASE_REFS); do \
	  repo=$${spec%:*}; branch=$${spec#*:}; \
	  test -d "$$repo/.git" || { echo "== $$repo: not checked out (run 'make pull')"; exit 1; }; \
	  test "$$(git -C "$$repo" branch --show-current)" = "$$branch" || { \
	    echo "== $$repo: $$branch is not checked out (run 'make pull')"; exit 1; }; \
	  test -z "$$(git -C "$$repo" status --porcelain)" || { \
	    echo "== $$repo: worktree is not clean"; exit 1; }; \
	  git -C "$$repo" show-ref --verify --quiet "refs/remotes/origin/$$branch" || { \
	    echo "== $$repo: origin/$$branch is unavailable locally (run 'make pull')"; exit 1; }; \
	  test "$$(git -C "$$repo" rev-parse "$$branch")" = "$$(git -C "$$repo" rev-parse "origin/$$branch")" || { \
	    echo "== $$repo: $$branch differs from local origin/$$branch (run 'make push')"; exit 1; }; \
	done
	@for r in $(HTTK_MODULES); do \
	  repo="$(MODULES_DIR)/$$r"; \
	  version="$$($(READ_PROJECT_VERSION) < "$$repo/pyproject.toml")" || exit 1; \
	  tag="v$$version"; \
	  if git -C "$$repo" show-ref --verify --quiet "refs/tags/$$tag"; then \
	    echo "== $$r: reusing existing $$tag"; \
	  else \
	    echo "== $$r: checking $$tag"; \
	    $(MAKE) -C "$$repo" release-prepare VERSION="$$tag" || exit 1; \
	    test -z "$$(git -C "$$repo" status --porcelain)" || { \
	      echo "== $$r: checks refreshed release inputs; rerun preparation before checking again"; exit 1; }; \
	  fi; \
	done
	@set -eu; \
	  site="$(MODULES_DIR)/$(HTTK_DOCS_REPOSITORY)"; \
	  temporary_tags=""; \
	  cleanup_tags() { \
	    for item in $$temporary_tags; do \
	      nested=$${item%%:*}; tag=$${item#*:}; \
	      git -C "$$nested" tag -d "$$tag" >/dev/null 2>&1 || true; \
	    done; \
	  }; \
	  trap cleanup_tags EXIT HUP INT TERM; \
	  for r in $(HTTK_MODULES); do \
	    source="$$(cd "$(MODULES_DIR)/$$r" && pwd)"; \
	    nested="$$site/submodules/$$r"; \
	    test -e "$$nested/.git" || { \
	      echo "== $(HTTK_DOCS_REPOSITORY): $$r is not initialized; rerun preparation"; exit 1; }; \
	    version="$$($(READ_PROJECT_VERSION) < "$$source/pyproject.toml")"; \
	    tag="v$$version"; \
	    if git -C "$$source" show-ref --verify --quiet "refs/tags/$$tag"; then \
	      commit="$$(git -C "$$source" rev-parse "$$tag^{}")"; \
	    else \
	      commit="$$(git -C "$$source" rev-parse develop)"; \
	    fi; \
	    test "$$(git -C "$$site" rev-parse "HEAD:submodules/$$r")" = "$$commit" || { \
	      echo "== $(HTTK_DOCS_REPOSITORY): $$r is not pinned to $$tag; rerun preparation"; exit 1; }; \
	    test "$$(git -C "$$nested" rev-parse HEAD)" = "$$commit" || { \
	      echo "== $(HTTK_DOCS_REPOSITORY): $$r checkout does not match its pin; rerun preparation"; exit 1; }; \
	    if git -C "$$nested" show-ref --verify --quiet "refs/tags/$$tag"; then \
	      test "$$(git -C "$$nested" rev-parse "$$tag^{}")" = "$$commit" || { \
	        echo "== $$r: $$tag does not identify the pinned commit"; exit 1; }; \
	    else \
	      git -C "$$nested" -c tag.gpgSign=false tag "$$tag" "$$commit"; \
	      temporary_tags="$$temporary_tags $$nested:$$tag"; \
	    fi; \
	  done; \
	  version="$$($(READ_PROJECT_VERSION) < "$$site/pyproject.toml")"; \
	  echo "== $(HTTK_DOCS_REPOSITORY): checking v$$version"; \
	  $(MAKE) -C "$$site" release-prepare VERSION="v$$version"; \
	  test -z "$$(git -C "$$site" status --porcelain)" || { \
	    echo "== $(HTTK_DOCS_REPOSITORY): checks changed release inputs; rerun preparation"; exit 1; }
	@version="$$($(READ_PROJECT_VERSION) < pyproject.toml)"; \
	  echo "== httk2: checking v$$version"; \
	  $(MAKE) release-prepare VERSION="v$$version" || exit 1; \
	  test -z "$$(git status --porcelain)" || { echo "== httk2: checks changed files"; exit 1; }

# This operates on refs rather than checking out main. Each repository push is
# atomic, so its main branch and release tag are published together.
release-merge-tag-and-push-main:
	@set -eu; for spec in $(HTTK_RELEASE_REFS); do \
	  repo=$${spec%:*}; branch=$${spec#*:}; \
	  name="$$(basename "$$(cd "$$repo" && pwd)")"; \
	  test -d "$$repo/.git" || { echo "== $$name: not checked out (run 'make pull')"; exit 1; }; \
	  echo "== $$name: fetching release refs"; \
	  refs=main; test "$$branch" = main || refs="$$refs $$branch"; \
	  git -C "$$repo" fetch origin $$refs --tags; \
	  version="$$(git -C "$$repo" show "$$branch:pyproject.toml" | $(READ_PROJECT_VERSION))"; \
	  tag="v$$version"; \
	  if git -C "$$repo" ls-remote --exit-code --tags origin "refs/tags/$$tag" >/dev/null 2>&1; then \
	    echo "== $$name: reusing existing remote $$tag"; continue; \
	  fi; \
	  git -C "$$repo" merge-base --is-ancestor "origin/$$branch" "$$branch" || { \
	    echo "== $$name: local $$branch is not based on origin/$$branch"; exit 1; }; \
	  test "$$branch" = main || git -C "$$repo" merge-base --is-ancestor origin/main "$$branch" || { \
	    echo "== $$name: $$branch cannot be fast-forwarded onto main"; exit 1; }; \
	  ! git -C "$$repo" show-ref --verify --quiet "refs/tags/$$tag" || { \
	    echo "== $$name: tag $$tag already exists"; exit 1; }; \
	done
	@set -eu; for spec in $(HTTK_RELEASE_REFS); do \
	  repo=$${spec%:*}; branch=$${spec#*:}; \
	  name="$$(basename "$$(cd "$$repo" && pwd)")"; \
	  version="$$(git -C "$$repo" show "$$branch:pyproject.toml" | $(READ_PROJECT_VERSION))"; \
	  tag="v$$version"; \
	  if git -C "$$repo" ls-remote --exit-code --tags origin "refs/tags/$$tag" >/dev/null 2>&1; then \
	    echo "== $$name: keeping existing $$tag"; continue; \
	  fi; \
	  echo "== $$name: signing and pushing $$tag"; \
	  git -C "$$repo" -c user.name="$(GIT_USER_NAME)" -c user.email="$(GIT_USER_EMAIL)" \
	    tag -s -m "$$tag" "$$tag" "$$branch"; \
	  if test "$$branch" = develop; then refs="develop:develop develop:main"; else refs="main:main"; fi; \
	  git -C "$$repo" push --atomic origin $$refs "refs/tags/$$tag" || { \
	    git -C "$$repo" tag -d "$$tag"; exit 1; }; \
	done
