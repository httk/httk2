# Releasing `httk2`

`httk2` is a metapackage: it contains no Python code of its own and only pins
the set of *httk₂* modules to install. Releases are built and published by
GitHub Actions. PyPI authentication uses Trusted Publishing, so the repository
does not need a stored PyPI API token.

## Release ordering

The metapackage must be released **after** the modules it depends on already
exist on PyPI at compatible versions. An `httk2` release resolves only if its
`Requires-Dist` entries can be satisfied from the index:

- `httk-core`, `httk-io`, and `httk-atomistic` must be published (at versions
  matching the ranges in `pyproject.toml`) before the base `httk2` release is
  installable.
- `httk-web` and `httk-optimade` must be published before the `web`,
  `optimade`, and `all` extras are meaningful; otherwise an
  `httk2[all]` install will fail to resolve.

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

Update `project.version` in `pyproject.toml`. From a Python 3.12 environment,
install the release tools and build the distribution:

```console
python -m pip install -e ".[release]"
make release-check
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
/tmp/httk2-test/bin/python -c "import httk.core, httk.io, httk.atomistic"
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
