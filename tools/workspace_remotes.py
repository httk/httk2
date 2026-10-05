"""Configure public fetch and authenticated push URLs for workspace repos.

The helper deliberately changes only local Git configuration.  Submodule
registrations remain authoritative for their update URL and are never edited.
"""

import argparse
import os
import re
import subprocess
import tempfile
from collections.abc import Callable, Iterable
from pathlib import Path

_GITHUB_SSH_SCHEME = re.compile(r"^ssh://git@github\.com/(?P<path>.+)$")
_GITHUB_SSH_SCPC = re.compile(r"^git@github\.com:(?P<path>.+)$")
_GITHUB_HTTPS = re.compile(r"^https://github\.com/(?P<path>.+)$")
_ProbeResult = bool | tuple[bool, str]
_Probe = Callable[[str], _ProbeResult]


def _github_path(url: str) -> str | None:
    """Return a GitHub repository path for a supported URL, if any."""

    for pattern in (_GITHUB_SSH_SCPC, _GITHUB_SSH_SCHEME, _GITHUB_HTTPS):
        match = pattern.fullmatch(url.strip())
        if match:
            path = match.group("path").rstrip("/")
            if path and path.count("/") == 1:
                return path
    return None


def github_https(url: str) -> str | None:
    """Return the public HTTPS form of a supported GitHub URL."""

    path = _github_path(url)
    return f"https://github.com/{path}" if path else None


def github_ssh(url: str) -> str | None:
    """Return the SSH form of a supported GitHub URL."""

    path = _github_path(url)
    return f"git@github.com:{path}" if path else None


def _isolated_probe_environment(home: str) -> dict[str, str]:
    """Build an environment with inherited Git configuration removed."""

    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("GIT_") and key not in {"SSH_ASKPASS", "SSH_AUTH_SOCK"}
    }
    environment.update(
        {
            "HOME": home,
            "XDG_CONFIG_HOME": home,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return environment


def _redact_probe_error(error: str) -> str:
    """Remove credentials from a Git probe diagnostic."""

    one_line = " ".join(error.split())
    return re.sub(r"(https?://)[^/@\s]+@", r"\1<redacted>@", one_line)


def _probe_public(url: str, timeout: float = 15.0) -> tuple[bool, str]:
    """Check a URL and return a safe diagnostic when it is not public.

    :param url: Candidate public repository URL.
    :param timeout: Maximum probe duration in seconds.
    :return: A success flag and a safe failure diagnostic.
    """

    with tempfile.TemporaryDirectory(prefix="httk-public-remotes-") as directory:
        environment = _isolated_probe_environment(directory)
        command = [
            "git",
            "-c",
            "credential.helper=",
            "-c",
            "core.askPass=",
            "-c",
            "http.extraHeader=",
            "ls-remote",
            url,
        ]
        try:
            result = subprocess.run(
                command,
                cwd=directory,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout,
                check=False,
            )
        except OSError as error:
            return False, f"could not run git: {error.strerror or error}"
        except subprocess.TimeoutExpired:
            return False, f"timed out after {timeout:g}s"
    if result.returncode == 0:
        return True, ""
    diagnostic = _redact_probe_error(result.stderr or "")
    return False, diagnostic or f"git ls-remote exited with status {result.returncode}"


def probe_public(url: str, timeout: float = 15.0) -> bool:
    """Check that ``url`` is readable without credentials.

    :param url: Candidate public repository URL.
    :param timeout: Maximum probe duration in seconds.
    :return: Whether anonymous ``git ls-remote`` succeeded.
    """

    return _probe_public(url, timeout)[0]


def _git(
    arguments: Iterable[str],
    repository: Path,
    *,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a Git command in ``repository`` with text output."""

    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        text=True,
        capture_output=True,
        check=check,
    )


def _repository_root(path: Path) -> Path | None:
    result = _git(["rev-parse", "--show-toplevel"], path)
    if result.returncode:
        print(f"== {path}: not a Git repository; skipped")
        return None
    return Path(result.stdout.strip()).resolve()


def _origin_url(repository: Path) -> str | None:
    result = _git(["config", "--get", "remote.origin.url"], repository)
    if result.returncode:
        return None
    return result.stdout.strip() or None


def _explicit_push_urls(repository: Path) -> list[str]:
    result = _git(["config", "--get-all", "remote.origin.pushurl"], repository)
    if result.returncode:
        return []
    return [line for line in result.stdout.splitlines() if line]


def _set_origin_fetch(repository: Path, url: str) -> None:
    _git(
        ["config", "--local", "--replace-all", "remote.origin.url", url],
        repository,
        check=True,
    )


def _set_submodule_url(repository: Path, key: str, url: str) -> None:
    _git(
        ["config", "--local", "--replace-all", f"{key}.url", url],
        repository,
        check=True,
    )


def _registered_submodules(repository: Path) -> list[tuple[str, str, Path]]:
    """Read submodule names, URLs and paths without modifying ``.gitmodules``."""

    if not (repository / ".gitmodules").is_file():
        return []
    result = _git(
        ["config", "--file", ".gitmodules", "--get-regexp", r"^submodule\..*\.path$"],
        repository,
    )
    if result.returncode:
        return []
    registrations = []
    for line in result.stdout.splitlines():
        key, separator, relative_path = line.partition("\t")
        if not separator:
            key, separator, relative_path = line.partition(" ")
        if not separator or not key.endswith(".path"):
            continue
        section = key.removesuffix(".path")
        url_result = _git(
            ["config", "--file", ".gitmodules", "--get", f"{section}.url"], repository
        )
        if url_result.returncode:
            continue
        url = url_result.stdout.strip()
        if url:
            registrations.append((section, url, (repository / relative_path).resolve()))
    return registrations


def _is_git_repository(path: Path) -> bool:
    if not path.is_dir() or not (path / ".git").exists():
        return False
    result = _git(["rev-parse", "--show-toplevel"], path)
    return (
        result.returncode == 0
        and Path(result.stdout.strip()).resolve() == path.resolve()
    )


class _Configurator:
    """Apply remote configuration while caching public probes."""

    def __init__(self, probe: _Probe = _probe_public) -> None:
        self.probe = probe
        self.probes: dict[str, tuple[bool, str]] = {}

    def _probe_result(self, url: str) -> tuple[bool, str]:
        if url not in self.probes:
            result = self.probe(url)
            self.probes[url] = result if isinstance(result, tuple) else (result, "")
        return self.probes[url]

    def _is_public(self, url: str) -> bool:
        return self._probe_result(url)[0]

    def _probe_failure(self, url: str) -> str:
        return self._probe_result(url)[1]

    def _configure_remote(self, repository: Path, source_url: str) -> None:
        fetch_url = github_https(source_url)
        if fetch_url is None:
            print(f"== {repository}: unsupported remote; skipped")
            return
        if not self._is_public(fetch_url):
            reason = self._probe_failure(fetch_url)
            suffix = f" ({reason})" if reason else ""
            print(f"== {repository}: public probe failed{suffix}; skipped")
            return

        _set_origin_fetch(repository, fetch_url)
        print(f"== {repository}: fetch URL configured for public access")
        push_url = github_ssh(source_url)
        if push_url is None:
            return
        if _GITHUB_SSH_SCHEME.fullmatch(source_url) or _GITHUB_SSH_SCPC.fullmatch(
            source_url
        ):
            push_url = source_url
        explicit = _explicit_push_urls(repository)
        if explicit:
            if push_url not in explicit:
                print(
                    f"== {repository}: preserving explicit push URL(s); skipped push update"
                )
            return
        _git(
            ["config", "--local", "--add", "remote.origin.pushurl", push_url],
            repository,
            check=True,
        )
        print(f"== {repository}: SSH push URL configured")

    def configure_tree(self, repository: Path, source_url: str | None = None) -> None:
        """Configure one repository and recurse through registered submodules."""

        if source_url is None:
            source_url = _origin_url(repository)
        if source_url is None:
            print(f"== {repository}: no origin remote; skipped")
        else:
            self._configure_remote(repository, source_url)

        for key, registered_url, child in _registered_submodules(repository):
            fetch_url = github_https(registered_url)
            if fetch_url is None:
                print(f"== {child}: unsupported registered URL; skipped")
            elif not self._is_public(fetch_url):
                reason = self._probe_failure(fetch_url)
                suffix = f" ({reason})" if reason else ""
                print(f"== {child}: public probe failed{suffix}; skipped")
            else:
                _set_submodule_url(repository, key, fetch_url)
            if _is_git_repository(child):
                self.configure_tree(child, registered_url)


def configure_repository(
    path: str | os.PathLike[str],
    *,
    probe: _Probe = _probe_public,
) -> None:
    """Configure a repository and its registered submodules.

    :param path: Repository directory.
    :param probe: Public URL probe, injectable for tests.
    """

    repository = _repository_root(Path(path).resolve())
    if repository is None:
        return
    _Configurator(probe).configure_tree(repository)


def _configure_targets(
    paths: Iterable[str],
) -> None:
    """Configure the explicitly supplied repositories once."""

    configurator = _Configurator()
    for path in paths:
        repository = _repository_root(Path(path).resolve())
        if repository is not None:
            configurator.configure_tree(repository)


def main(arguments: list[str] | None = None) -> int:
    """Run the workspace remote helper command line interface."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="+", help="repository directories")
    options = parser.parse_args(arguments)
    _configure_targets(options.repo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
