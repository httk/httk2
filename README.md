# httk2

![Status: beta](https://img.shields.io/badge/status-beta-orange)

> **⚠️ BETA**
>
> The organization of *httk₂* packages and their APIs is not yet stable, and there may be backward-breaking changes between v2.1.* versions.

The High-Throughput Toolkit (*httk₂*) is an open-source toolkit for
*preparing* and *running* automated computational workflows,
*analyzing* the results, *storing* them in a global and/or in a
personalized database, and providing *UI and API access to the data.*
Presently, *httk₂* is primarily targeted at atomistic calculations in
materials science and electronic structure, but aims to be more
broadly useful outside those areas.

This is the `httk2` metapackage repository. It contains no Python code of its own, but provides two functions:

* It handles the `httk2` packaging for PyPI (pip).

* It provides a Makefile for managing an *httk₂* install from our Git repositories, helpful both for developers and for users who prefer distribution via Git, or want to use the develop version.

## Installation

To install the package created from this repository from PyPI:

```console
pip install httk2
```
(But this should preferably be done in a Python virtual environment, see the [httk website](https://httk.org) for various recommended installation options.)

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

Simulation-code support comes as separate `httk-workflow-<code>` distributions.
Install one through an extra, for example `pip install "httk2[vasp]"` (extras:
`abinit`, `cp2k`, `gromacs`, `lammps`, `orca`, `phonopy`, `qe`, `vasp`), all
eight with `pip install "httk2[codes]"`, or directly with
`pip install httk-workflow-<code>`. *httk-workflow-phonopy* brings in
*httk-workflow-vasp*.

The modules share the PEP 420 native namespace package `httk`; there is no
separate `httk2` import package.

For a local checkout, the same dependency set can be installed with
`pip install .`.

Individual modules can also be installed on their own (for example
`pip install httk-core` for a minimal, dependency-free core); see each module
repository for its optional extras.

## Installing the development version and developing *httk₂*

This repository's `Makefile` doubles as a workspace manager for *httk₂* modules:

```console
make checkout          # initial setup; alias for checkout-develop
make checkout-develop  # clone missing repositories; select develop where available
make checkout-main     # clone missing repositories; select main where available
make ssh-push-remotes  # configure SSH pushes while retaining public HTTPS fetches
make fetch             # git fetch in every managed repository
make pull              # fast-forward current branches from their configured upstreams
make update-submodules # update the documentation site's pinned submodule checkouts
make push              # git push in every repository, including this one
make install-minimal   # editable-install the httk modules without any extras
make install           # editable-install the workspace with the [default] extras
make install-develop   # ... adding the [dev] tooling extras
make install-full      # ... adding the [ci], [docs] and [release] extras
make install-vasp      # clone httk-workflow-vasp if missing, then make install
make install-phonopy   # ... likewise (also clones httk-workflow-vasp, which it needs)
make install-codes     # ... the same for all simulation-code support
```

For example, a development workspace with VASP support is set up by:

```console
make checkout
make install-vasp
make install-develop
```
Run these as separate commands, not `make install-vasp install-develop`, since `make` determines the managed repositories when it starts.

Notes:

* `checkout` is an alias for `checkout-develop`.

* The `checkout*` Makefile targets clone missing modules (and the
  documentation repository) over public HTTPS from
  `https://github.com/httk/...`.  `HTTK_GIT_BASE` can override the
  clone base. These targets select the requested branch in this
  repository and every checkout under `modules/` when that branch
  exists locally or on `origin`.  Repositories without that branch
  keep their current branch; a new clone starts on the remote's
  default.  Simulation-code support (`httk-workflow-<code>`) is not
  cloned by `checkout*` (see below).  The documentation repository,
  `httk.github.io`, selects `main` in both modes. Remote lookup errors
  fail the command rather than being treated as absent branches.

* Developers can issue `make ssh-push-remotes` to configure SSH pushes
  while retaining public HTTPS fetches.

* The install targets require an activated virtual environment or a
  non-base conda environment and install the release modules, the
  documentation site and this metapackage editable, each with those of
  the selected extras it declares; other development repositories
  (such as the site starter and workflow-package collections) are not
  installed.

* Modules split their development dependencies: no extra means
  minimal, all have a `default` extra, `dev` holds the tooling
  (pytest, ruff, pydoclint, pyright, mypy), while `ci` holds the
  optional integrations needed for a full `make ci`, which adds a lot
  of dependencies, e.g., ase, jobflow/atomate2, the DuckDB/ClickHouse
  drivers, and the DSP schema validators.

* `install-minimal` leaves out the httk2 metapackage (because its
  requirements name the modules' `[default]` extras).

* `install-develop` installs all modules with `[dev]`, which includes
  development tools but deliberately leaves out the extensive set of
  dependencies needed to run the full CI.

* Installing a smaller level into an existing environment does not remove packages.

* `install-<code>` (`install-abinit`, `install-cp2k`,
  `install-gromacs`, `install-lammps`, `install-orca`,
  `install-phonopy`, `install-qe` or `install-vasp`) clones the
  respective repository into `modules/` when it is missing, selecting
  the branch the `httk-workflow` checkout is on where it exists, and
  then runs `install` (`install-phonopy` also clones
  *httk-workflow-vasp*, which it depends on). `install-codes` does the
  same for all of them.

* Existing checkouts keep their current branch. Because `install` and
  the other workspace targets cover every release module under
  `modules/`, code support added once is afterwards installed by
  `install`, `install-develop` and `install-full` and is updated by
  `pull`.

* Every repository found under `modules/` is managed. One carrying the
  module template's release infrastructure (`tools/check_release.py`)
  is included in coordinated release discovery; branch selection also
  covers other development repositories. Moving a repository into
  `modules/` is enough to include it.

* `pull` uses each current branch's configured upstream, including
  this metapackage checkout, with fast-forward-only updates and tag
  fetching. It does not clone missing repositories, select branches,
  probe public URLs, synchronize submodule URLs, or update submodule
  checkouts. A branch without an upstream requires you to configure
  one explicitly. `fetch`, `pull` (after the metapackage pull
  succeeds), and `push` continue through individual module failures
  and exit non-zero if any repository failed.

* `ssh-push-remotes` is an explicit, one-time configuration command
  for this checkout, the repositories under `modules/`, and their
  registered Git submodules. It checks GitHub HTTPS access without
  credentials before setting an `origin` fetch URL and an SSH push URL
  in local Git configuration. Private, unreachable, and unsupported
  URLs are skipped. Registered submodule SSH URLs supply their push
  destinations; existing custom push destinations are preserved. No
  committed `.gitmodules` files are changed. Run the helper again
  after adding repositories or changing visibility. Registrations
  inside an uninitialized submodule become discoverable after that
  submodule is initialized; rerun the helper to configure those
  descendants. The former `httk.publicRemotes` setting is no longer
  used.

* `update-submodules` separately updates the documentation site's
  submodules to its committed revisions using existing URL
  configuration. If registered URLs change, run `git -C
  modules/httk.github.io submodule sync --recursive` explicitly,
  followed by `make ssh-push-remotes` to restore public HTTPS fetches
  and SSH pushes.

* `install` refuses to run without an activated virtual environment or
  a non-base conda environment.

## For *httk₂* maintainers: releasing a new version

Mark the modules to release with local `vX.Y.Z-rc0` tags on `develop` (on `main` in repositories without `develop`), with `project.version` already set to the final `X.Y.Z`. Then run:

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
