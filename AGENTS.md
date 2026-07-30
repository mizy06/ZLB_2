# AGENTS.md

## Repository Commands

- Prerequisites: Python 3.12, Node.js 22, and pnpm 10.14.0.
- Install: `python3.12 -m venv .venv && .venv/bin/python -m pip install -r backend/requirements.txt && (cd frontend && corepack enable && pnpm install --frozen-lockfile)`
- Run locally (backend): `.venv/bin/python -m uvicorn backend.app.main:app --reload`
- Run locally (frontend): `cd frontend && pnpm dev`
- Relevant tests: `.venv/bin/python -m unittest discover -s backend/tests -v && (cd frontend && pnpm test)`
- Lint/static sanity: `git diff --check && .venv/bin/python -m compileall -q backend/app backend/tests`
- Typecheck: `cd frontend && pnpm exec tsc -b --pretty false`
- Build: `cd frontend && pnpm build`
- Production image: `docker build --build-arg GIT_SHA="$(git rev-parse HEAD)-dirty" -t zlb-mindmap-agent .`

## GitHub First: Do Not Reinvent Solutions

- This is mandatory: before debugging or implementing any bug fix, integration workaround, missing capability, compatibility fix, or non-trivial utility, search GitHub for an existing solution first.
- Search the current repository and the relevant upstream dependency repositories. Check issues (open and closed), pull requests (open and merged), discussions, code, commits, releases, changelogs, and maintained examples.
- Search using the exact error message, affected symbols/API names, dependency names, and the versions used by this repository. Use `gh search issues`, `gh search prs`, `gh search code`, and direct upstream repository searches where practical.
- Prefer a maintained, licensed, version-compatible upstream fix, established library, or repository-native implementation over custom code. Adapt it minimally to existing repository patterns.
- Do not start a custom implementation until the GitHub search is complete. If no suitable solution exists, briefly record which repositories/queries were checked and why the available solutions were rejected before implementing the smallest local solution.
- Never copy code blindly. Verify license compatibility, maintenance status, security implications, dependency/version compatibility, and tests before adopting it.
- In progress updates and the final report, cite the relevant GitHub issue, PR, commit, release, or implementation used. When none is suitable, report the search evidence and the reason custom code was necessary.

## Think Before Coding

- Inspect relevant code, tests, and existing patterns before editing.
- Do not silently guess when ambiguity materially affects behavior or design.
- State important assumptions and briefly surface meaningful tradeoffs.
- For non-trivial work, make a short plan with a verification step for each phase.
- For trivial and unambiguous changes, proceed directly.
- Define observable acceptance criteria before implementation.

## Simplicity First

- Implement the smallest complete solution.
- Do not add speculative features, abstractions, or configurability.
- Prefer existing repository patterns and dependencies.
- Do not add production dependencies without explicit justification.
- Reuse the GitHub solution identified during research whenever it is compatible.
- If the change becomes unexpectedly large, stop and reassess the approach.

## Keep Changes Surgical

- Touch only code required by the request.
- Do not perform unrelated refactors, formatting, renames, or cleanup.
- Preserve code and comments you do not fully understand.
- Match the surrounding style.
- Remove only unused code created by your own change.
- Inspect the final diff for accidental changes.
- Do not overwrite or revert existing user changes in a dirty worktree.

## Verification

- For bugs, add a reproducing test when practical.
- Run focused checks during iteration and required checks before completion.
- Run the backend test suite for backend or shared contract changes.
- Run `pnpm test`, typecheck, and build for frontend or shared contract changes.
- For UI changes, verify visually at relevant desktop and mobile viewport sizes.
- For deployment changes, validate `docker compose -f compose.prod.yml config --quiet` with the required token environment variables supplied safely.
- Do not claim success without evidence.
- Report commands run, results, and any remaining limitations.

## Repository Boundaries

- Do not edit generated or local-runtime paths: `frontend/dist/`, `frontend/.test-dist/`, `frontend/node_modules/`, `*.tsbuildinfo`, `__pycache__/`, `.pytest_cache/`, `.data/`, `runtime/`, or `backend/uploads/`.
- Do not modify public HTTP APIs, request/response schemas, or persisted graph contracts without approval.
- Do not change SQLite schemas, migrations, or persisted-data compatibility without approval.
- Do not expose, print, copy, or commit secrets, tokens, credentials, decrypted environment files, age identities, or files matched by the repository secret ignore rules.
- Follow `backend/app/cplus_pipeline.py`, `backend/app/agents.py`, `backend/app/blackboard.py`, and `backend/app/mindmap_engine/` for backend architecture patterns.
- Follow existing components and utilities in `frontend/src/` for frontend behavior and styling.
- Treat `docs/CPLUS_IMPLEMENTATION.md` and `docs/MINDMAP_ROOT_CAUSE_ANALYSIS.md` as implementation context, but verify claims against current code and tests.

## Definition of Done

- The requested behavior is implemented.
- GitHub was searched first for an existing implementation or fix, and the adopted solution or no-fit conclusion is reported.
- Relevant tests pass.
- Lint/static sanity, typecheck, and build pass when applicable.
- No unrelated changes remain in the diff.
- Documentation is updated only when behavior or public interfaces changed.
- Any unverified behavior, external dependency, operational step, or remaining risk is stated explicitly.
