# httk2

The high-throughput toolkit (`httk`) is a modular Python toolkit for materials
science. This repository provides the `httk2` metapackage: it contains no Python
code of its own and installs the standard set of httk v2 modules.

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

The modules share the PEP 420 native namespace package `httk`; there is no
separate `httk2` import package.

## Optional modules

Web and OPTIMADE support can be installed separately:

```console
pip install "httk2[web]"
pip install "httk2[optimade]"
```

Install every module selected by this metapackage with:

```console
pip install "httk2[all]"
```

For a local checkout, the same dependency sets can be installed with
`pip install .` and `pip install ".[all]"`.
