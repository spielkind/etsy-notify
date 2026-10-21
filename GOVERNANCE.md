# Governance

Shop Notify is a small community project. This document describes who takes decisions
and how the project continues if a maintainer becomes unavailable.

## Roles and responsibilities

| Role | Who | Responsibilities |
|---|---|---|
| **Owner and lead maintainer** | [@spielkind](https://github.com/spielkind) | Direction and roadmap, final decisions, releases, repository settings, security reports |
| **Maintainer** | [@Tomalak](https://github.com/Tomalak) | Reviewing and merging pull requests, triaging issues, releases; takes over if the owner is unavailable (see below) |
| **Contributor** | anyone | Reporting bugs, proposing features, submitting pull requests according to [CONTRIBUTING.md](CONTRIBUTING.md) |

Maintainers are listed here and have write access to the repository. New maintainers
are added by the owner after a history of good contributions; maintainers who are no
longer active are moved out of this list.

## Decisions

- Day-to-day changes are made through pull requests. A pull request is merged by a
  maintainer once all required checks pass and the change fits the project's scope.
- Larger changes (new features, breaking changes, new dependencies on external services)
  are discussed in an issue first. The roadmap is tracked with the
  [`roadmap` label](https://github.com/spielkind/shop-notify/issues?q=is%3Aopen+label%3Aroadmap).
- Maintainers try to reach consensus; if that is not possible, the lead maintainer
  decides.
- Security reports are handled privately as described in [SECURITY.md](SECURITY.md).

## Continuity

The project must be able to continue within a week if a maintainer becomes unavailable:

- Both maintainers can handle issues, merge pull requests and **publish releases**:
  release tags can be pushed by every maintainer; they must be signed and point to a
  commit on `main`, which only changes through pull requests with passing checks.
  Releases are built and published entirely by GitHub Actions – no personal credentials
  or local build machines are needed.
- [@Tomalak](https://github.com/Tomalak) is the designated
  [successor](https://docs.github.com/en/account-and-profile/setting-up-and-managing-your-personal-account-on-github/managing-access-to-your-personal-repositories/maintaining-ownership-continuity-of-your-personal-accounts-repositories)
  of the owner's account and can take over ownership of the repository (including its
  settings and the container images) if the owner can no longer act.
- All project knowledge lives in the repository: documentation, CI/CD workflows,
  release process ([CONTRIBUTING.md](CONTRIBUTING.md#releasing)) and this document.

## Code of conduct

All participants are expected to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
