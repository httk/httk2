# Releasing `httk2`

`httk2` is a metapackage: it contains no Python code of its own and only pins
the set of *httk₂* modules to install. Releases are built and published by
GitHub Actions. PyPI authentication uses Trusted Publishing, so the repository
does not need a stored PyPI API token.

## Release ordering

The metapackage must be released **after** the modules it depends on already
exist on PyPI at compatible versions. An `httk2` release resolves only if its
`Requires-Dist` entries can be satisfied from the index:

- `httk-core`, `httk-atomistic`, `httk-store`, `httk-serve`,
  `httk-analyse`, and `httk-workflow` must all be published (at versions
  matching the ranges in `pyproject.toml`) before the `httk2` release is
  installable.

Release the individual module distributions first, confirm they install from
PyPI, then release the matching `httk2` version.

## One-time setup

1. Create accounts on [PyPI](https://pypi.org) and
   [TestPyPI](https://test.pypi.org), and enable two-factor authentication.
2. In the GitHub repository settings, create environments named `pypi` and
   `testpypi`. Configure a required reviewer for `pypi` (and optionally for
   `testpypi`); restricting the `pypi` environment to tags matching `v*` is
   also recommended.
3. On PyPI, add a pending GitHub Trusted Publisher with these values:

   - PyPI project name: `httk2`
   - Owner: `httk`
   - Repository: `httk2`
   - Workflow: `release.yml`
   - Environment: `pypi`

4. Add the corresponding pending publisher on TestPyPI, using the environment
   `testpypi` instead.

A pending publisher creates the project during its first upload. It does not
reserve the project name before then.

## Prepare and check a release

The module repositories, aggregate documentation, and `httk2` metapackage can
be prepared and published together from this repository. The managed
repositories are checked out under `modules/` by default.

1. Update and commit each repository's `pyproject.toml`, including the intended
   `project.version` and released dependency floors. Use `develop` for the six
   runtime modules and `main` for `httk.github.io` and `httk2`.
2. Check out or update those branches:

   ```console
   make pull
   ```

3. Run the coordinated release preparation:

   ```console
   make release-prepare-all
   ```

   For a version that is already tagged, this reuses the released commit and
   does not rerun its release preparation. For a new version, it runs the
   runtime module's complete isolated release preparation, including normal
   tests on Python 3.12, 3.13, and 3.14. It then pins the
   `httk.github.io` submodules to those exact release commits, regenerates and
   checks its ecosystem manifest and documentation lock, and commits the
   resulting documentation snapshot. Finally, it checks the `httk2`
   distribution using its own `project.version`.

   `release-check-all` is an alias for this same operation; do not run both.

   Runtime release preparation may refresh committed documentation inputs. If
   it does, the aggregate target stops; commit those exact changes on
   `develop` and repeat this step.

4. If every preparation succeeds, fast-forward each runtime module's remote
   `main` to `develop`, create each signed `v<project.version>` tag, and push
   the release refs atomically within each repository:

   ```console
   make release-merge-tag-and-push-main
   ```

   Runtime modules are pushed first, followed by `httk.github.io` and `httk2`.
   The target updates Git refs directly and does not change branches or read
   the worktrees. Runtime versions and tags come from `develop`, which is also
   pushed to `main`; documentation and metapackage versions and tags come from
   `main`. It stops before creating any tags if a local release branch is not
   based on its remote, a runtime `main` cannot be fast-forwarded, or a release
   tag already exists.

   Repositories whose `v<project.version>` tags already exist remotely are
   left unchanged. This permits one block release to combine unchanged 2.1.0
   modules with new 2.1.1 modules. Do not run `make push` between preparation
   and this step: this target pushes each release branch together with its tag.

5. In GitHub, create and publish releases using the existing tags. Publish the
   six runtime module releases in dependency order and wait for their PyPI
   uploads before publishing the `httk2` release. The `httk.github.io` tag push
   starts the versioned aggregate documentation deployment directly.

The pushes are atomic within each repository. Git cannot make pushes across
separate repositories atomic, so if a later remote push fails, retry it after
checking which earlier repositories were already published.

To check only the `httk2` metapackage, install its release tools and run:

```console
python -m pip install -e ".[release]"
make release-prepare VERSION=v2.1.1
```

This builds an isolated sdist/wheel and runs strict package-metadata checks. The
resulting files are written to `dist/`. There is no code or documentation to
check for a metapackage.

Versions on package indexes are immutable. Use a new development or release
candidate version when repeating an upload, for example `2.0.0rc1` followed by
`2.0.0`.

## TestPyPI

Run the **Publish package** workflow manually in GitHub Actions. A manual run
publishes to TestPyPI only. To retry a TestPyPI upload without committing a version bump, pass the
optional `version_suffix` workflow input (e.g. `.post1` or `rc2`); it is
appended to `project.version` for that build only.
When the workflow run has completed (approving the
`testpypi` environment first, if it has a required reviewer), test the artifact
in a fresh environment. Because the metapackage's dependencies live on PyPI,
allow pip to fall back to it for them:

```console
python -m venv /tmp/httk2-test
/tmp/httk2-test/bin/python -m pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ httk2==2.0.0
/tmp/httk2-test/bin/python -c "import httk.core, httk.atomistic, httk.atomistic.io, httk.analyse.generic, httk.analyse.matsci"
```

Replace `2.0.0` with the version being tested.

## PyPI

1. Confirm that the module dependencies are already published on PyPI at
   compatible versions (see **Release ordering**).
2. Confirm that `make release-check` succeeds on the exact commit to release.
3. Push the commit and create a GitHub release whose tag is `v` followed by the
   package version, for example `v2.0.0`.
4. Publish the GitHub release and approve the protected `pypi` environment.
5. Verify the release from a fresh environment with `pip install httk2`.

The workflow rejects a Git tag that does not match `project.version`, rebuilds
the distributions from the tagged source, checks them, and publishes them via
PyPI Trusted Publishing.
