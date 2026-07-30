# vNext S0 Clean-Room Implementation

- Date: 2026-07-29
- Status: S0 contract freeze implemented; shadow only
- Governing decision: `docs/MINDMAP_SYSTEM_REDESIGN.md`, ADR-01
- Legacy baseline: `297da939835dc9b748a33bd80d368702d7de687d`

> Phase record: this file preserves the S0 completion point. The current
> consolidated S0-S4 engineering status, latest verification counts, and
> remaining No-Go items are tracked in `docs/VNEXT_IMPLEMENTATION_MATRIX.md`.

## 1. Boundary

The vNext implementation is isolated under `backend/vnext/`. It does not
import or call the legacy C+ semantic pipeline, normalizer, topology solver,
review service, visual analysis, page knowledge extractor, blackboard, public
schemas, or persisted graph models.

The legacy runtime does not import vNext during S0. There is no route,
database migration, public response-field change, production publish pointer,
or legacy result adapter in this phase.

The standalone entry point is:

```bash
.venv/bin/python -m backend.vnext.cli export-schemas --check
.venv/bin/python -m backend.vnext.cli validate \
  --contract ReplanRequest \
  --input /path/to/replan-request.json
.venv/bin/python -m backend.vnext.cli shadow-store \
  --contract ReplanRequest \
  --input /path/to/replan-request.json \
  --owner tenant-a \
  --root /path/to/vnext-shadow \
  --role bottom_up_region_auditor \
  --producer omission-auditor \
  --producer-version 1.0.0
```

`shadow-store` uses a separate filesystem root. Owner directory names are
SHA-256 scopes, artifact IDs are random opaque IDs, and payloads and envelopes
are immutable RFC 8785 JSON files. Payload and envelope files become visible
together through an atomic directory rename; abandoned pending directories
have an explicit reconciliation method. It never opens `blackboard.sqlite3`.
This is a single-host shadow mechanism, not a substitute for the later
outbox/CAS/durable control plane.

## 2. Frozen Contracts

The following Pydantic bindings and JSON Schema 2020-12 files are frozen:

| Contract | Version |
| --- | --- |
| `SourceObservationIR` | `1.0.0` |
| `SourceInventory` | `1.0.0` |
| `RegionPlan` | `1.0.0` |
| `RegionSplitCertificate` | `1.0.0` |
| `ReplanRequest` | `1.0.0` |
| `ClaimLedger` | `1.0.0` |
| `OmissionAudit` | `1.0.0` |
| `CanonicalExplicitGraph` | `0.1.0` |
| `DiagnosticProjection` | `0.1.0` |
| `ArtifactEnvelope` | `1.0.0` |

All bindings use frozen models, reject unknown fields, reject non-finite
numbers, and use tuples for archived collections. The deterministic exporter
writes `backend/vnext/contracts/jsonschema/manifest.json` with each schema ID,
version, file, and canonical digest.

## 3. Enforced Invariants

- Stable source IDs are derived from source hash, parser major, object kind,
  and deterministic locator.
- Artifact IDs are random and content-independent; identical payloads do not
  reveal cross-owner equality.
- Courseware, external, human, and system evidence use separate namespaces.
- Artifact envelopes bind payload type, schema ID/version, owner, digest, and
  authorized writer role.
- Page role and reading order remain interpretation hypotheses.
- Source Inventory is independent of Claim Ledger and retains its own external
  denominator.
- Only Global Structure Planner and Recursive Region Planner can write
  `RegionPlan`.
- Bottom-up Region Auditor can write only `ReplanRequest`.
- Split acceptance requires at least two supported children, a supported
  common parent, explainable boundaries, comparable sibling granularity, and
  complete Source Inventory accounting.
- Node count, token count, page capacity, and maximum depth are not semantic
  split or stop evidence.
- High-importance omissions block the Claim gate.
- Core claims carry separate Claim Atomizer and Claim Fidelity Verifier
  producer identities; the extractor cannot certify its own claim.
- Canonical v0 accepts only explicit or outline-anchor concepts and
  courseware-direct or outline `topic_contains` relations.
- External-only, retrieval-only, aggregate, evidence-free, and unverified
  relations cannot be accepted.
- Parentless concepts remain parentless/unresolved; no root fallback exists.
- Canonical hierarchy may have multiple accepted parents but must be acyclic.
- A rejected edge can reopen only as a new relation with `supersedes` and a
  novel courseware evidence digest.
- Projection parents must be accepted direct Canonical relations. View-only
  aggregation uses the `view:` namespace.

## 4. Incident And Adversarial Oracles

The executable aldehydes/ketones oracle freezes:

- retention of `10.1` through `10.4` outline candidates;
- `research_aside`, `returns_to`, `review`, exercise, and instruction
  hypotheses;
- reaction provenance on pages 27 and 34;
- rejection of the known fragmentary top-level labels;
- prohibition on promoting "complete the following conversion" to a core
  courseware fact;
- monotonic parent-edge veto and unresolved parentless claims.

`p0_adversarial_contract_cases.json` covers every category in section 19 of
the redesign. S0 controls execute directly. Search, durable orchestration, and
legacy down-conversion cases remain explicitly `blocked_pending_stage`; they
are not counted as implemented or passed production capabilities.

## 5. Legacy Compatibility Freeze

The current legacy contract is frozen by two RFC 8785/SHA-256 snapshots:

- OpenAPI 3.1: 23 paths, 48 component schemas,
  `sha256:111e35217a1e0c1896ec8b860658b5f9be544e36cb2132686fac5ed73ec116ea`
- Selected public model schemas:
  `sha256:f3899ad3363a7b6b0ba3ef9ac42097f2d95d1e8a02bef92caeb30237ecf235f1`

The snapshot test also asserts that no vNext contract appears in legacy
OpenAPI.

## 6. GitHub-First Record

GitHub CLI was unavailable, so the current repository history, GitHub REST
issue/PR search, upstream source, releases, and license files were checked.

Adopted:

- Pydantic's native `model_json_schema()` exporter. Its upstream documentation
  states Draft 2020-12 support:
  https://github.com/pydantic/pydantic/blob/main/docs/concepts/json_schema.md
- Trail of Bits `rfc8785.py` v0.1.4 for JCS:
  https://github.com/trailofbits/rfc8785.py/releases/tag/v0.1.4
  The project is Apache-2.0, pure Python, dependency-free, and supports Python
  3.8+. It is pinned in both requirements and constraints:
  https://github.com/trailofbits/rfc8785.py

Considered and rejected for S0:

- Import Linter provides maintained forbidden/layer contracts, but one small
  repository AST test covers this package boundary without adding a
  production or development dependency:
  https://github.com/seddonym/import-linter
- GitHub searches for `SourceObservationIR`, `RegionSplitCertificate`,
  `minimum_replan_ancestor_id`, and the project-specific
  `DiagnosticProjection` semantics found no compatible implementation.
  The unrelated matches did not implement source inventory accounting,
  top-down-only structure authority, or minimum-ancestor replanning.

No upstream code was copied into the domain contracts.

## 7. Verification

Focused command:

```bash
.venv/bin/python -m unittest discover \
  -s backend/tests -p 'test_vnext*.py' -v
```

Final verification:

- vNext focused suite: 56 tests passed.
- Complete backend suite: 592 tests passed, 1 skipped.
- `git diff --check`: passed.
- `compileall` for `backend/app`, `backend/vnext`, and `backend/tests`: passed.
- deterministic schema check: no changes.
- `pip check`: no broken requirements.

S1 source adapters, live model calls, search, public routes, legacy result
conversion, and production publication remain out of scope.
