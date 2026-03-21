# v0.2.0 — Initial public paper-aligned release

This release prepares the project for direct publication as a GitHub repository while keeping the codebase aligned with the submitted manuscript.

## Highlights

- Repository cleaned for public release: stale caches, checked-in test artifacts, and machine-specific leftovers removed.
- README rewritten as a proper open-source project overview with reproducibility scope, quick-start commands, and licensing notes.
- MIT license added for source code and original repository documentation.
- GitHub Actions workflows added for continuous integration and release-artifact builds.
- Contribution guidance and third-party data notice added.
- Package metadata and in-code versioning aligned to `0.2.0`.

## Included in this release

- Paper-aligned benchmark scenarios and canonical `_fw` result tags
- Frozen manuscript tables and appendix exports under `reports/`
- Regression tests, including checks for selected Table 3, Table 6, and Table 9 values
- Public-data provenance manifests under `data/raw/`

## Scope notes

This is a reproducible research release, not a general-purpose energy-system toolkit. The repository keeps frozen benchmark artifacts for auditability. Full end-to-end recomputation still depends on the optimization stack and solver environment defined by the project configuration files.

## Upgrade notes from the cleaned internal snapshot

- Added release-facing metadata and governance files.
- Removed checked-in `.pytest_cache/` and `tests/__pycache__/` remnants.
- Standardized the project version to `0.2.0` in package metadata and source.
