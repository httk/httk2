PYTHON ?= python3
DIST_DIR ?= dist

.PHONY: clean dist-clean dist dist-check release-check

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
