# Releasing `httk2`

`httk2` is a metapackage: it contains no Python code of its own and only pins
the set of *httk₂* modules to install. Releases are built and published by
GitHub Actions. PyPI authentication uses Trusted Publishing, so the repository
does not need a stored PyPI API token.

## Release ordering and cycles

Every release gate resolves `httk-*` requirements from PyPI and reads the
dependencies' release documentation from `docs.httk.org`: the documentation
lock, the committed intersphinx inventories, the isolated wheel and test
environments, and the GitHub Actions release workflows. Nothing is verified
against local checkouts, because that is not what users install. So a module
whose new version raises its floor on a sibling (for example `httk-serve`
requiring `httk-store>=2.1.2`) cannot be locked, checked, or tagged until that
sibling version is published on PyPI. The same applies to the `httk2`
metapackage, whose `Requires-Dist` entries must all be installable from the
index.

The coordinated targets below handle this by **deferring** rather than
failing: an untagged module whose `httk-*` requirements do not resolve from
PyPI is skipped with a `deferring` message. Runtime tags are provisional until
PyPI accepts that exact project version; a failed final build may therefore be
fixed, rechecked, and retagged. The `httk.github.io` snapshot and the `httk2`
metapackage wait until every selected runtime version is on PyPI, so they never
pin a provisional tag. Releasing modules that evolve together is consequently
a loop of release cycles: each cycle tags what is publishable, those tags are
published through GitHub, and the next cycle picks up modules that were waiting
for them. The loop ends when the final step reports that nothing new was tagged.

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
repositories are checked out under `modules/` by default. The release targets
act on every repository there that carries the httk-module-template release
infrastructure (`tools/check_release.py`), whether or not it is one of the six
default modules; repositories without it are development checkouts that only
`make pull` and `make push` touch. A release module that is not a submodule of
`httk.github.io` is released on its own and skipped when the aggregate
documentation snapshot is pinned.

Step 1 is done once. Steps 2 to 7 form one release cycle; repeat the cycle
until step 6 reports `Nothing new was tagged; the release cycle is complete`.
A release where no module depends on an unpublished sibling completes in one
cycle. This requires `uv` on `PATH`, as do the module release gates.

1. Update and commit each repository's `pyproject.toml`, including the intended
   `project.version` and released dependency floors. Use `develop` for the
   runtime modules and `main` for `httk2`. The `httk.github.io` version is not
   set by hand: the aggregate documentation snapshot is versioned as the
   `httk2` release it documents, and preparation sets it.
2. Check out or update those branches:

   ```console
   make pull
   ```

   This also initializes the `httk.github.io` submodules at the commits recorded
   by that repository. Later preparation repins them from the local runtime
   checkouts and does not contact remote Git repositories.

3. Run the coordinated release preparation:

   ```console
   make release-prepare-all
   ```

   For each new runtime version, this refreshes its documentation lock and
   inventories without running the expensive release gates. These refreshes
   use package indexes and published documentation but do not contact remote
   Git repositories. A new version whose `httk-*` requirements are not yet on
   PyPI is reported as `deferring` together with the blocking requirements
   and left untouched for a later cycle. If the inputs change, the target
   stops: review, commit, and sign them on `develop`, then repeat this step.
   Once the runtime repositories are clean, it pins the `httk.github.io`
   submodules to the selected release commits, sets its `project.version` to
   the `httk2` version, regenerates its ecosystem manifest and documentation
   lock, and commits that snapshot, but only after the exact selected version
   of every runtime module is present on PyPI. If that version is already
   tagged for `httk.github.io` and the snapshot still changed, preparation stops: bump
   the `httk2` version, or repair the published documentation instead. While any
   module is deferred or still provisional, `httk.github.io` and `httk2` are
   deferred instead and this step ends after the runtime modules.

4. Sign any generated commits, then push all candidate branches:

   ```console
   make push
   ```

5. Run the complete isolated release checks:

   ```console
   make release-check-all
   ```

   The target performs no remote Git operations, though its isolated package
   installation and documentation gates use package indexes and published
   documentation. It requires every candidate
   branch to match the local `origin/<branch>` ref recorded by the preceding
   push. Each new runtime version runs its normal tests on Python 3.12, 3.13,
   and 3.14, along with its CI, documentation, distribution, dependency, and
   isolated-wheel checks. It then checks the pinned aggregate documentation
   snapshot and the `httk2` distribution once all runtime versions are on
   PyPI. Published versions are reused; provisional tagged versions are checked
   again so a corrected candidate cannot bypass the release gates. Deferred
   modules are skipped in the same way as during preparation. The final release
   target refreshes and validates remote refs and PyPI publication state
   immediately before publishing.

6. If every check succeeds, fast-forward each runtime module's remote
   `main` to `develop`, create each signed `v<project.version>` tag, and push
   the release refs atomically within each repository:

   ```console
   make release-merge-tag-and-push-main
   ```

   Runtime modules are pushed first, followed by `httk.github.io` and `httk2`.
   This step runs where Git can authenticate; it needs only Git and Python
   3.12, not an httk installation or `uv`. It uses Git remotes and PyPI's JSON
   API. It identifies deferred modules from their committed inputs: a
   provisional module whose
   documentation lock on `develop` is stale for its `pyproject.toml` was not
   prepared, either because preparation deferred it or because preparation
   was never run, and is not tagged. The target updates Git refs directly and
   does not change branches or read the worktrees. Runtime versions and tags
   come from `develop`, which is also pushed to `main`; documentation and
   metapackage versions and tags come from `main`. It stops before creating any
   tags if a local release branch is not based on its remote or a runtime
   `main` cannot be fast-forwarded.

   Published `v<project.version>` tags that already exist remotely are left
   unchanged. For an existing provisional tag, the target verifies that the
   remote tag identifies `develop` and advances `main` to that commit. This
   permits a failed candidate to be fixed and retagged before PyPI acceptance,
   and permits one block release to combine unchanged 2.1.0 modules with new
   2.1.1 modules. Deferred modules are not tagged;
   `httk.github.io` and `httk2` are also withheld while any selected runtime
   version is absent from PyPI. The target ends with either
   `Tagged: ...`, listing the new tags; a waiting message while provisional
   runtime releases remain; or `Nothing new was tagged; the release cycle is
   complete`, which ends the loop.

   A runtime tag is provisional until PyPI accepts its exact project version.
   If the final GitHub release build fails before upload, fix and sign the
   branch, delete or move the tag locally and on `origin`, and repeat the cycle
   from step 2; the aggregate snapshot has not yet been created. Each runtime
   tag push deploys that version's release documentation, and the deploy job
   replaces earlier documentation while the version is absent from PyPI. Once
   the version is on PyPI, its tag and documentation are immutable and changes
   require a new package version (or the approved documentation repair workflow
   when only the deployed documentation is wrong).

7. In GitHub, create and publish releases using the tags listed in step 6.
   Publish the runtime module releases in dependency order and wait for their
   PyPI uploads. Each runtime tag push also starts that module's release
   documentation deployment, which deferred dependents need for their
   inventories. If step 6 reported deferred modules, wait until the new
   versions are visible on PyPI and at `https://docs.httk.org/<module>/v<version>/`,
   then start the next cycle at step 2: the published modules are reused by
   their tags, stale aggregate submodule tag caches are synchronized to those
   final tags, and the previously deferred modules are prepared, checked, and
   tagged. The aggregate documentation and `httk2` are prepared and tagged only
   after every selected module version has been published. The `httk2` release
   is then created from that final cycle. The `httk.github.io` tag push starts
   the versioned aggregate documentation deployment directly.

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
   compatible versions (see **Release ordering and cycles**).
2. Confirm that `make release-check` succeeds on the exact commit to release.
3. Push the commit and create a GitHub release whose tag is `v` followed by the
   package version, for example `v2.0.0`.
4. Publish the GitHub release and approve the protected `pypi` environment.
5. Verify the release from a fresh environment with `pip install httk2`.

The workflow rejects a Git tag that does not match `project.version`, rebuilds
the distributions from the tagged source, checks them, and publishes them via
PyPI Trusted Publishing.
