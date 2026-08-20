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
on all httk₂ modules at once:

```console
make checkout   # clone any missing module repositories into modules/
make fetch      # git fetch in every module repository
make pull       # git pull --ff-only in every module repository
make push       # git push in every module repository
make install    # editable-install every module (with its default extra)
                # into the currently activated virtual environment
```

`checkout` clones over SSH from `git@github.com:httk/...` and skips
repositories already present, so it is safe to re-run. `fetch`, `pull`, and
`push` operate on whatever branch each repository currently has checked out,
continue past individual failures, and exit non-zero if any repository failed.
`install` refuses to run without an activated virtual environment, and installs
the modules in dependency order so each editable install finds its httk
dependencies already in place.
