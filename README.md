# httk2

![Status: Pre-release](https://img.shields.io/badge/status-pre--release-red)

> **⚠️ PRE-RELEASE**
>
> The version assigned to *httk2* meta-package designates the overall version of *httk₂*,
> and thus starts at v2.0.0. However, versions v2.0.* are to be considered
> prereleases, and semantic versioning will not be used until v2.1.0.

The high-throughput toolkit (*httk₂*) is a modular Python toolkit for materials
science. This repository provides the `httk2` metapackage: it contains no Python
code of its own; instead, it installs the standard set of httk₂ modules, each
with its default feature set.

## Installation

Install the standard modules from PyPI:

```console
pip install httk2
```

This installs:

- [`httk-core`](https://github.com/httk/httk-core), providing `httk.core`
- [`httk-io`](https://github.com/httk/httk-io), providing `httk.io`
- [`httk-atomistic`](https://github.com/httk/httk-atomistic), providing
  `httk.atomistic`
- [`httk-data`](https://github.com/httk/httk-data), providing `httk.data`
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
