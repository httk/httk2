PYTHON ?= python3
DIST_DIR ?= dist

# Module-workspace helpers: check out and operate on all httk₂ module
# repositories under $(MODULES_DIR). The list is in dependency order, which
# `install` relies on so each editable install finds its httk dependencies
# already present in the venv.
MODULES_DIR ?= modules
HTTK_GIT_BASE ?= git@github.com:httk
HTTK_MODULES ?= httk-core httk-store httk-atomistic httk-analyse httk-serve httk-workflow

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

.PHONY: clean dist-clean dist dist-check release-check checkout fetch pull push install

checkout:
	@mkdir -p $(MODULES_DIR)
	@for r in $(HTTK_MODULES); do \
	  if [ -d "$(MODULES_DIR)/$$r/.git" ]; then \
	    echo "== $$r: already present"; \
	  else \
	    echo "== $$r: cloning"; \
	    git clone "$(HTTK_GIT_BASE)/$$r.git" "$(MODULES_DIR)/$$r" || exit 1; \
	  fi; \
	done

fetch:
	$(call git_foreach,fetch)

pull:
	$(call git_foreach,pull --ff-only)

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
