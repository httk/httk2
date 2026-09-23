# Releasing *httk₂*

The coordinated workflow checks a whole release batch before any member needs
to be published. Code validation and documentation preparation are separate:
fixing a cross-reference or regenerating an inventory does not repeat the
Python matrix. GitHub still builds and validates each published distribution.

## Select and check a batch

Requirements: Python 3.12+, Git, make, uv, Node/npm for modules with JavaScript,
network access for Python tools/packages and published inventories, and a Git
signing key for the final publication command. The code matrix uses Python
3.12, 3.13 and 3.14; uv obtains missing interpreters.

1. Commit the intended module changes on `develop`, including the chosen final
   `project.version`, then run `make pull` in this repository.
2. Tag each module to release at its current `develop` HEAD:

   ```console
   git -C modules/httk-core tag v2.3.4-rc0
   ```

   The tag is a local selection marker. The corresponding `pyproject.toml`
   must declare `version = "2.3.4"`, **not** a prerelease version.
   Unselected modules use the latest stable-tagged commit on `origin/main`
   (or local `main` when no remote-tracking branch exists). Selection follows
   main-branch commit history, not tag dates. An old rc0 away from HEAD does
   not select a module. No versions or dependency floors are changed for you.
   `make pull` refreshes main and tags before selection; stable final tags are
   treated as your release records, without querying PyPI publication status.

3. Run:

   ```console
   make release-check-all
   ```

   The helper snapshots the chosen commits and installs the complete batch
   together in a fresh environment for each Python version. It runs every
   selected module's `make ci`, including modules reused from stable releases,
   and stops at the first failure. Distribution and isolated wheel checks
   retain packaging coverage. **This phase does not build or refresh docs.**
   Incompatible dependency requirements fail resolution; unpublished members
   of this batch are supplied locally rather than deferred to another cycle.

4. For code failures, fix and commit the affected module, move its rc0 marker
   to the new HEAD, and repeat the code check:

   ```console
   git -C modules/httk-core tag -f v2.3.4-rc0
   make release-check-all
   ```

   Keep these markers local; do not use `git push --tags`. A final `vX.Y.Z`
   release tag is never moved by this workflow.

The batch and gate evidence are recorded in ignored `.release-batch.json`;
complete logs, isolated sources, environments and wheels remain in the printed
temporary directory. Keep both until publication completes. The later commands
use this same checkout and evidence. `RELEASE_STATE=/path/to/state.json`
selects another local report. Starting another code check invalidates the prior
success, even if the new selection or an early gate fails.

## Prepare documentation

Run:

```console
make release-docs-build
```

The helper checks the recorded batch, generates portable documentation locks
constrained to its exact module versions, and strictly builds candidate docs
in documentation-dependency order. Candidate inventories come from these
local builds; inventories for unchanged modules come from their exact published
version. Committed external inventories remain in use. Cross-links point to
the final public URLs, for example
`https://docs.httk.org/httk-core/v2.3.4/`, and inventories retain the final
release's project/version headers. No warning suppressions are added.

Successful generated module locks and inventories are copied back without
staging or committing. Fix documentation errors and rerun this command.
Documentation edits under `docs/` and root Markdown/reStructuredText prose
reuse the code result; changes to source, tests, examples, build tools,
workflows, or dependency metadata require a fresh rc0 and code check.

The aggregate site needs the final module commit hashes. Therefore finish in
this order:

1. Review, commit and push the generated module documentation on `develop`.
   Leave the rc0 markers at the original code-tested commits.
2. Run `make release-aggregate-docs-build`. This separate stage prepares and
   strictly checks the aggregate site against the final module commits, then
   updates its lock, ecosystem manifest and
   submodule checkouts without staging or committing them.
3. Review, commit and push the aggregate site's changes on `main`, including
   its gitlinks.

A successful `release-docs-build` reports `modules-ready`; module documentation
is complete. `release-aggregate-docs-build` uses that evidence without rerunning
the module builds or code matrix. Publication requires both stages to pass.
Committing identical verified files does not invalidate the evidence. Changing
module documentation requires `release-docs-build` again; changing only the
aggregate site requires only `release-aggregate-docs-build` again. Changing code
requires another code check. Aggregate retries preserve successful module docs.

This replaces `release-prepare-all`. The existing single-module
`make release-prepare VERSION=vX.Y.Z` remains available for independent
releases but is not part of this batch workflow.

## Tag and publish

After committing and pushing the verified module and aggregate changes:

```console
make release-merge-tag-and-push-main
```

The helper preflights the complete batch before publishing any member. It
requires unchanged code and docs, clean working trees, pushed candidate
branches, consistent aggregate gitlinks, and a fast-forward from each
module's `main` to its verified `develop` commit. Divergent branches stop
the command; resolve them manually and revalidate if their content changes.

For candidate modules only, it advances local `main` without switching the
working branch, creates the signed final `vX.Y.Z` tag, and atomically pushes
`main` plus the tag to `origin`. It does not publish GitHub releases or
upload packages. Unselected modules, the metapackage and the aggregate site's
release tags are left alone. Those repositories can be released separately
when desired; aggregate preparation does not choose a new site version.

The documentation and publication commands print release groups, for example:

```text
== Group 1
httk-core v2.3.4
== Group 2
httk-atomistic v2.3.4
httk-store v2.3.4
httk-workflow v2.3.4
== Group 3
httk-analyse v2.3.4
httk-serve v2.3.4
```

Create the GitHub releases for a group together. Wait until its packages are
available on PyPI and its versioned documentation has deployed before releasing
the next group. Runtime docs deployment starts on **published GitHub releases**,
so pushing the batch's final tags does not try to install unpublished siblings.
GitHub's package release gates and strict docs builds remain in place.

Git pushes are atomic per repository, not across repositories. A later failure
can leave earlier members published. The report retains progress; fix the
transport or signing problem and retry the same command. Matching final tags
are reused on retries; conflicting tags are errors. Do not move rc0 markers,
edit verified files, or delete the evidence to work around a publication error.

Browser and live database acceptance remain separate where required. Optional
skips in a module's CI are visible in the logs; a successful batch is not a
claim that unconfigured external services were tested.

## Release the metapackage separately

Once its dependencies are published, install the release tools and check the
metapackage:

```console
python -m pip install -e ".[release]"
make release-prepare VERSION=v2.1.3
```

Use its actual `project.version`. This builds an sdist and wheel and runs
strict package-metadata checks. Commit and tag the intended version, push it,
and publish its matching GitHub release. The existing release workflow verifies
the tag/version match and uploads through PyPI Trusted Publishing.

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
