# httk2

![Status: Pre-release](https://img.shields.io/badge/status-pre--release-red)

> **⚠️ PRE-RELEASE**
>
> The version assigned to *httk2* meta-package designates the overall version of *httk₂*,
> and thus starts at v2.0.0. However, versions v2.0.* are to be considered
> prereleases, and semantic versioning will not be used until v2.1.0.

The high-throughput toolkit (*httk₂*) is a modular Python toolkit for materials
science. This repository provides the `httk2` metapackage: it contains no Python
code of its own; ; instead, it installs a standard set of httk₂ modules, with
additional modules available through optional extras.

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
- [`httk-analyse`](https://github.com/httk/httk-analyse), providing
  `httk.analyse`
- [`httk-workflow`](https://github.com/httk/httk-workflow), providing
  `httk.workflow` and the `httk workflow` command tree

The modules share the PEP 420 native namespace package `httk`; there is no
separate `httk2` import package.

## Optional modules

Web publishing and OPTIMADE serving are provided together by `httk-serve`:

```console
pip install "httk2[serve]"
```

Install every module selected by this metapackage with:

```console
pip install "httk2[all]"
```

For a local checkout, the same dependency sets can be installed with
`pip install .` and `pip install ".[all]"`.
