# Contributing

Start with [AGENTS.md](AGENTS.md) and the [architecture](docs/architecture.md).

Run `python3 scripts/install_hooks.py` once per clone, then work on a `<type>/<topic>` branch such as `feat/insider-parser` or `fix/dividend-dates`. main is protected locally and integrates through PRs. See the [branch policy](docs/engineering/branch-policy.md); local hooks do not replace GitHub rulesets.

## Workflow

1. Pick a task from the [plan](docs/plan.md) (`Px` / `Px.n`) or a `REPO` maintenance task. Read its local note in `.research/` when there is one.
2. Inspect the existing code and do the [readiness pass](docs/engineering/task-readiness.md): the smallest coherent result and the evidence needed to accept it.
3. Implement following the [coding standards](docs/engineering/coding-standards.md) and the [security/data rules](docs/engineering/security-and-data.md). Keep new research in `.research/`; document what the code relies on in `docs/`.
4. Run focused checks while working (`uv run pytest tests/test_x.py`), then `python3 scripts/verify.py`. See [testing and verification](docs/engineering/testing-and-verification.md).
5. Review the diff and follow [code review](docs/engineering/code-review.md). Open a PR only when asked, using the template.

Use English identifiers and code comments where new code is written; existing modules use Romanian comments and CLI messages, and user-facing text (CLI output, dashboard) stays Romanian. Keep one language per file.

## Toolchain

- [uv](https://docs.astral.sh/uv/) manages Python 3.12 (`.python-version`) and dependencies (`pyproject.toml`, `uv.lock`). `uv sync` installs everything, including dev tools.
- `uv run playwright install chromium` once, for the BVB page collectors.
- Ruff formats and lints (`uv run ruff format`, `uv run ruff check --fix`); pytest runs the tests.
- The repository checks in `scripts/` use only the Python standard library and run with any Python 3.9+.

## Dependencies and decisions

Add dependencies with `uv add` (or `uv add --dev`) and commit `uv.lock`. The verifier syncs in locked mode, so a stale lockfile fails.

Before adding a dependency, check its documentation, license and maintenance, and record the reason in the PR. Use [the decision template](docs/engineering/decisions/template.md) for a material architecture, data-source or security tradeoff.

## Definition of done

- The named behavior works, with evidence appropriate to its risk; data changes are spot-checked on real data.
- Provenance, idempotency, point-in-time correctness and polite source access are preserved where affected.
- Formatting, lint and tests pass. Skipped or unavailable checks are listed as such.
- Schema changes are additive (`CREATE ... IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`) or come with a rebuild procedure.
- Docs, README and `uv.lock` match the implementation. No secrets, collected data, unrelated changes or fabricated completion claims.

See [maintainer setup](docs/engineering/maintainer-setup.md) for GitHub settings that repository files cannot activate.
