# Contributing

Thanks for your interest! Bug reports, ideas and pull requests are welcome – please
check the [roadmap](https://github.com/spielkind/shop-notify/issues?q=is%3Aopen+label%3Aroadmap)
and the open issues first. For security problems see [SECURITY.md](SECURITY.md).

## Development setup

Requires [uv](https://docs.astral.sh/uv/); it installs a matching Python (3.14+) if needed.

```sh
uv sync
uv run pre-commit install   # gitleaks, hadolint, typos, ruff, mypy, actionlint, zizmor and file checks
```

Run the checks:

```sh
uv run ruff format && uv run ruff check
uv run mypy src tests
uv run pytest               # with branch coverage; the project is kept at 100 %
```

`uv run shop-notify test-notify` sends a sample notification to the targets in your
`.env`/`notify.yml` without needing an Etsy key.

The tests never use the network or your local `.env`: Etsy is mocked with
[respx](https://lundberg.github.io/respx/), notifications go to a fake `shoptest://`
Apprise service (see `tests/conftest.py`).

## Pull requests

- One topic per pull request; link the issue (`Closes #12`).
- Add tests for new behaviour and keep the coverage at 100 %.
- Add a line to `CHANGELOG.md` under *Unreleased* for user-visible changes.
- Update the README, `.env.example` and `notify.example.yml` when configuration changes.
- Use a [Conventional Commits](https://www.conventionalcommits.org/) title
  (`feat: …`, `fix: …`, `docs: …`, `ci: …`, `chore: …`) – pull requests are squash-merged
  and the title becomes the commit message.

CI must pass before merging: secret scan (gitleaks), lint (ruff, mypy, actionlint, zizmor, hadolint,
typos), tests on all supported
Python versions, dependency audit and the Docker build for amd64 and arm64.

## Dependency updates

Dependabot proposes grouped updates (weekly for Python packages and actions, monthly for
pre-commit hooks) after a cooldown of 7 days. Patch and minor updates are merged
automatically once all required checks pass; major updates need a manual review. Merges
don't create a release – they are shipped with the next one (use a patch release for
urgent security fixes). Merges done by the auto-merge workflow don't trigger further
workflows; the weekly scheduled Docker run rebuilds the `main` image anyway.

## Weekly maintenance run

Every Monday at 05:00 UTC the Docker workflow rebuilds `main`, scans the released
`latest` image and deletes old commit images (`sha-…`; the newest 10, releases, `latest`
and `main` are kept). Vulnerabilities found there don't fail the run – check
*Security → Code scanning* or the job summary. Start it manually under *Actions → Docker →
Run workflow*; the cleanup then defaults to a dry run.


## Releasing

Changes are listed in [`CHANGELOG.md`](CHANGELOG.md) under *Unreleased*. To publish a release:

```sh
uv version --bump minor                 # or patch / major / rc; updates pyproject.toml and uv.lock
# CHANGELOG.md: rename "Unreleased" to "[X.Y.Z] - YYYY-MM-DD", add a new empty "Unreleased"
git commit -am "chore(release): X.Y.Z"
git tag -a vX.Y.Z -m "vX.Y.Z"           # SemVer notation, e.g. v1.0.0-rc.2
git push --follow-tags
```

The tag triggers the release workflow (checks that it matches the package version and
creates a GitHub release from the changelog section – a pre-release for `-rc`/`-beta`
versions) and publishes the Docker images `X.Y.Z`, `X.Y` and `latest`. The release gets the
wheel, the source archive and a CycloneDX SBOM attached, all with a signed build provenance
attestation (`gh attestation verify <file> --owner spielkind`); the Sigstore bundle of the
attestation is attached as `shop-notify-<version>.sigstore.json` for offline verification. Releases are immutable on GitHub:
once published, their tag and files can't be changed – fixes always need a new version. Release tags are
protected and cannot be moved or deleted.
