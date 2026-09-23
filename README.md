# httk2

![Status: Early beta](https://img.shields.io/badge/status-early--beta-orange)

> **⚠️ EARLY BETA**
>
> This is an early beta release of *httk₂*. The organization of the packages
> and their APIs should not yet be regarded as stable, and may change between
> releases.

The high-throughput toolkit (*httk₂*) is a modular Python toolkit for materials
science. This repository provides the `httk2` metapackage: it contains no Python
code of its own; instead, it installs the standard set of *httk₂* modules, each
with its default feature set.

## Installation

Install the standard modules from PyPI:

```console
pip install httk2
```

This installs:

- [`httk-core`](https://github.com/httk/httk-core), providing `httk.core`
- [`httk-atomistic`](https://github.com/httk/httk-atomistic), providing
  `httk.atomistic` (including file I/O: `httk.atomistic.io`)
- [`httk-store`](https://github.com/httk/httk-store), providing `httk.store`
- [`httk-serve`](https://github.com/httk/httk-serve), providing `httk.serve`
  (web publishing and OPTIMADE serving)
- [`httk-analyse`](https://github.com/httk/httk-analyse), providing
  `httk.analyse`
- [`httk-workflow`](https://github.com/httk/httk-workflow), providing
  `httk.workflow` and the `httk workflow` command tree

Each module is installed with its `default` extra, which selects that module's
recommended optional features (for example numpy-backed numerics and `spglib`
symmetry recognition).

The modules share the PEP 420 native namespace package `httk`; there is no
separate `httk2` import package.

For a local checkout, the same dependency set can be installed with
`pip install .`.

Individual modules can also be installed on their own (for example
`pip install httk-core` for a minimal, dependency-free core); see each module
repository for its optional extras.

## Developing httk₂

This repository's `Makefile` doubles as a small workspace manager for working
on all *httk₂* modules and the aggregate documentation site at once:

```console
make checkout   # clone missing repositories and check out release branches
make fetch      # git fetch in every managed repository
make pull       # check out and fast-forward every release branch
make push       # git push in every repository, including this one
make install    # editable-install the workspace, including development,
                # documentation, release, and optional integration extras
```

`checkout` clones the six default modules over SSH from
`git@github.com:httk/...` when they are missing. Every repository found under
`modules/` is managed: one that carries the httk-module-template release
infrastructure (`tools/check_release.py`) is a release module and is kept on
`develop`, `httk.github.io` is kept on `main`, and any other repository is a
development repository that `fetch`, `pull`, and `push` handle on whatever
branch it has checked out. Moving a repository into `modules/` is all it takes
to include it; adopting the module template later promotes it to a release
module. `pull` also keeps this metapackage checkout on `main`.
`fetch` and `push` continue past individual failures and exit non-zero if any
repository failed.
`install` refuses to run without an activated virtual environment. It installs
every declared extra from every checkout with a `pyproject.toml`, the aggregate
documentation checkout, and this metapackage in one resolution. This supplies the Python
dependencies used by release preparation and the broadest local test coverage.
Tests that exercise external database servers or browser runtimes still require
those services or tools to be started separately.

## Releasing a batch

Mark the modules to release with local `vX.Y.Z-rc0` tags on `develop`, with
`project.version` already set to the final `X.Y.Z`. Then run:

```console
make release-check-all                 # one isolated code matrix, no docs
make release-docs-build                # strict docs pinned to the tested batch
# Commit and push the module documentation changes.
make release-aggregate-docs-build      # aggregate docs at final module commits
# Commit and push the aggregate documentation changes.
make release-merge-tag-and-push-main    # signed final tags; prints release groups
```

Unselected modules use their latest stable-tagged main-branch commits.
Documentation corrections reuse the code result. See [RELEASING.md](RELEASING.md)
for the commit ordering, retained reports, retry rules and GitHub publication.
