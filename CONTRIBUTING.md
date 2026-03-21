# Contributing

Thank you for considering a contribution.

This repository is a paper-aligned research artifact, so correctness and manuscript consistency matter more than feature velocity.

## Before you open a pull request

- Search existing issues and pull requests first.
- Keep changes narrow and well scoped.
- Prefer incremental refactors over large structural rewrites.
- Do not add machine-specific files, caches, editor state, or large temporary downloads.

## Paper-alignment rules

Please be especially careful when touching any of the following:

- files under `reports/` that correspond to manuscript tables,
- frozen scenario outputs under `data/scenarios/`,
- helper scripts that regenerate released figures or canonical tables, and
- tests that pin manuscript-facing values.

If your change intentionally updates a released benchmark output, explain why that change is necessary and what manuscript-facing consequence it has.

## Recommended local checks

Run the lightweight regression suite before submitting:

```bash
pytest -q
```

If you change packaging or release metadata, also inspect:

- `README.md`
- `pyproject.toml`
- `.github/workflows/`

## Commit and pull request guidance

- Use descriptive commit messages.
- Summarize the motivation, change, and validation in the pull request body.
- Mention whether the change affects paper-facing outputs, scenario definitions, or only repository hygiene.

## What usually belongs elsewhere

The following are generally out of scope for this repository unless clearly tied to the paper workflow:

- experimental notebooks that are not part of the released workflow,
- alternative modeling branches that are not discussed by the manuscript, and
- large raw archives that can be recovered from the public-source manifests.
