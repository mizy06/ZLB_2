# Multi-document Visual/Text Editorial Pipeline

## Status

Approved design, 2026-08-23.

## Context

The web client was adapted from the Kimi Code web UI and now submits one or
more uploaded documents to the mindmap backend. The current backend has two
partially overlapping paths:

- the PPTX editorial pipeline, which already has a global editor, parallel
  reviewers, revisions, Responses-session context caching, and model events;
- the C+ pipeline, which accepts multi-document parameters at the HTTP/job
  boundary but currently receives only the first path in its LangGraph state,
  and does not consume the frontend `loop_config`.

The current editorial path also rejects non-PPTX inputs, while the generic
render aggregation helper can return an incomplete `RenderResponse`. These
boundaries explain the observed failures:

- mixed uploads can reach a PPTX-only function and fail late;
- ordinary multi-document jobs can silently process only the first document;
- a single-agent loop with no reviewers can still enter a forced revision;
- the first visible model tool call appears late while rendering, parsing, and
  context preparation happen without a unified early status;
- an initial Responses request may fail and fall back to a slower Chat stream
  without making that transition clear in the activity stream.

The approved direction is to reuse the editorial PPT/PPTX chain as the common
agent loop, while making images optional model input:

- renderable documents contribute visual pages;
- text-only documents contribute bounded, source-labelled text;
- the same main-editor, reviewer, revision, compaction, and finalization
  protocol handles both.

## Goals

1. Process every uploaded document, in stable input order, without silently
   dropping all but the first.
2. Treat PDF, PPTX, and DOCX (including legacy Office files after the existing
   conversion step) as visual-capable inputs.
3. Treat TXT, MD, and Markdown as text inputs without fabricating images.
4. Support mixed visual/text bundles by combining page images and labelled text
   context in one editorial run.
5. Make single-agent and multi-agent modes materially different for every
   supported input set.
6. Reuse the existing editorial reviewer, revision, context compaction, model
   fallback, and graph finalization behavior.
7. Show early preparation status and accurate first model-call events.
8. Preserve public HTTP response shapes, graph contracts, and the ability to
   read existing graph versions.
9. Provide focused regression tests for routing, aggregation, mode semantics,
   event projection, fallback, and multi-document evidence.

## Non-goals

- Replacing the editorial chain with a new cross-format supervisor.
- Changing the public `/api/jobs` request or `JobView` response schema.
- Changing SQLite tables or graph-version serialization contracts.
- Adding a new model provider or production dependency.
- Forcing text-only inputs through image rendering.
- Claiming that a rendering failure has been repaired by inventing visual
  evidence.

## Architecture

The existing `editorial_ppt_pipeline` remains the orchestration owner, but its
input boundary becomes format-neutral:

```text
uploaded files
    -> input classification
    -> DocumentBundle
         -> visual pages (optional)
         -> text context (always when extractable)
         -> stable document manifest
    -> editorial pipeline
         -> draft
         -> configured parallel review
         -> conditional revision
         -> context compaction between rounds when needed
         -> validation and graph-version finalization
```

The pipeline will receive an internal `EditorialInputBundle` containing:

- `source_paths`: all stored input paths;
- `filenames`: original user-visible names in the same order;
- `document_manifest`: stable per-document identity, type, page count, and
  source coordinate metadata;
- `visual_pages`: optional rendered pages with global and source-local
  coordinates;
- `native_visuals`: extracted PPTX assets where available;
- `text_context`: source-labelled parsed blocks/chunks;
- `human_guidance`: the existing normalized user instruction and refinement
  context.

`EditorialInputBundle` is an internal Python type. It is not added to the
public HTTP schema or persisted graph contract.

### Input routing

The route is based on document capability, not on whether every suffix is
`.pptx`:

| Input set | Model payload | Editorial path |
| --- | --- | --- |
| TXT/MD/Markdown only | text JSON | editorial text mode |
| One or more PDF/PPTX/DOCX | images plus available text | editorial visual mode |
| Visual plus text files | images plus labelled text | editorial mixed mode |

Legacy `.doc` and `.ppt` files are converted by the existing upload validation
step before classification. Their original names remain in the manifest.

If a visual-capable file cannot be rendered but has extractable text, the run
continues as text context for that document and records
`visual_render_degraded`. If a bundle has neither usable pages nor usable text,
the run fails explicitly before a model call.

### Visual rendering and aggregation

`render_documents()` will return a complete render collection:

- a collection-level `render_id` and filename;
- all pages with stable global page numbers;
- source filename, source type, source-local page/slide number, and global
  page number;
- native assets and warnings;
- a manifest written under the collection asset directory.

Each source document is rendered using the existing renderer. PDF rendering
uses the current PDF raster path. PPTX rendering and native visual extraction
remain unchanged. DOCX rendering uses the already-supported headless Office
conversion capability to create a PDF intermediary, then uses the PDF raster
path. Temporary conversion artifacts are not exposed as user documents.

The aggregate collection must preserve the asset directory assumptions used by
visual analysis and crop requests. Page URLs and crop references must resolve
through the collection manifest, and a collection response must never omit the
required `RenderResponse.render_id` or `RenderResponse.filename`.

### Text context

Every parsed block is wrapped with a stable source boundary:

```text
[document: notes.md]
...
[/document: notes.md]
```

For visual documents, extracted text is included when available and is
associated with its source page/slide. For text-only documents, the text is the
primary input. Chunking and overlap remain metadata; overlap markers are not
copied into extractable document content.

The prompt builder must receive the document manifest and text context
separately from the user instruction so user guidance cannot overwrite source
boundaries.

## Agent modes

The frontend continues to submit the existing `loop_config`. The backend
interprets it consistently for visual, mixed, and text-only runs.

### Single agent

- One global editor draft call.
- Local schema, evidence, topology, and graph validation remain mandatory.
- No reviewer role is started when the configured round has no reviewer models.
- No revision is started solely because the loop is marked custom.
- Finalization follows immediately after validation unless a local repair is
  required by the existing contract.

### Multi-agent

- Reviewer roles are selected from the configured round:
  `content_omission`, `pruning`, `multilevel_structure`, and the existing
  structural verification role.
- Independent reviewers run concurrently where their inputs do not depend on
  one another.
- Reviewers use images only when visual pages exist. Text-only runs use the
  same reviewer prompts with text/structure inputs and never include empty
  image fields.
- A revision occurs only when reviewer output contains actionable blocker or
  major issues, or when the configured loop explicitly requires another
  non-empty review round.
- Every role and round emits model start, delta, complete, or error events.

The existing reviewer and revision code remains the source of role behavior;
the change is the input adapter and the loop conditions that prevent an empty
review packet from forcing a pointless revision.

## Context and latency

The current editorial context mechanism becomes input-aware:

- initial context accounting includes all text blocks and all visual pages;
- each model call updates current tokens, maximum tokens, usage ratio, and
  total call count;
- at the high-water threshold, the existing compaction call summarizes the
  current graph, reviewer consensus, unresolved issues, document manifest, and
  human guidance;
- later rounds receive the compacted summary plus only the source context
  needed for that role;
- text-only runs compact only text and structured state;
- visual runs retain the selected visual pages and their source coordinates;
- compaction events include before/after token counts and the trigger.

The job event stream will add early preparation events:

- `agent_started`: the run has been accepted by the execution pipeline;
- `context_preparing`: files are being classified, rendered, parsed, or
  assembled.

These are activity events, not fake model calls. `model_start` is emitted only
immediately before the first real model request. Responses fallback remains
available, but the fallback start and the original model error are visible as
separate events.

## Error handling and degradation

- Classification failure: terminal job failure in `starting`, with a stable
  user-facing error.
- Per-document rendering failure with text available: continue with text and
  record a degraded component.
- Per-reviewer model failure: retain successful reviewer results, record the
  role-level error, and continue multi-agent review when possible.
- Main draft failure: use the existing fallback path; if it also fails, fail
  the job rather than emitting an empty graph.
- Compaction failure: retain the last valid graph and reviewer state, mark
  context degradation, and stop only when the next request cannot fit the
  model budget.
- No route may silently send a non-PPTX path into a PPTX-only validation
  branch.

## Compatibility

- Keep `/api/jobs`, `/api/jobs/{id}`, `/api/jobs/{id}/events`, and existing
  upload/refinement routes unchanged.
- Keep `JobView`, `MindMapResult`, node, edge, evidence, and graph-version
  response shapes unchanged.
- Store new routing and context fields in the existing run/job manifest only.
- Read old manifests with defaults:
  `agent_mode=legacy`, `input_mode=legacy`, and an empty document manifest
  when fields are absent.
- Do not alter SQLite schema or migration behavior.
- Keep the existing frontend event reducer compatible with old event streams;
  unknown optional preparation events must not break terminal job handling.

## Verification

### Backend tests

1. Classification matrix for PPTX, PDF, DOCX, TXT, MD, all-visual bundles,
   all-text bundles, and mixed bundles.
2. Multi-document parsing includes every filename and every source boundary.
3. Render collection always validates as a complete `RenderResponse`.
4. Global page numbering preserves source-local page/slide references.
5. Text-only requests contain no image content parts.
6. Visual requests contain page images and source-labelled text context.
7. Mixed requests contain both visual and text inputs.
8. Single-agent runs produce no reviewer or empty-packet revision calls.
9. Multi-agent runs execute configured reviewers concurrently and isolate one
   reviewer failure.
10. Context accounting and compaction preserve the document manifest and
    human guidance.
11. Old graph versions and old manifests remain readable.
12. Failed rendering falls back to text when possible and fails explicitly
    otherwise.

### Frontend tests

1. Preparation events display immediately and do not count as model calls.
2. Model start/delta/complete/error events render exactly once.
3. Single/multi mode state remains scoped to its session.
4. Mixed, text-only, and visual terminal states show the correct result or
   degradation.
5. SSE reconnect does not duplicate activity rows or lose terminal events.

### Required commands

Once implementation is complete and the required runtimes are available:

```text
.venv/bin/python -m unittest discover -s backend/tests -v
cd frontend && pnpm test
git diff --check
.venv/bin/python -m compileall -q backend/app backend/tests
cd frontend && pnpm exec tsc -b --pretty false
cd frontend && pnpm build
```

The current workspace does not contain the repository `.git` directory, and
the current machine does not have the required `.venv` or `pnpm` command
available. Those environment limitations must be reported rather than
presenting the corresponding checks as passed.

## Acceptance criteria

The change is complete when:

1. Every uploaded document appears in the internal document manifest and in
   the resulting evidence or an explicit degraded record.
2. PDF/DOCX/PPTX inputs use visual pages when rendering succeeds.
3. TXT/MD inputs use text-only payloads without empty image placeholders.
4. Mixed bundles use both visual and text context in one editorial run.
5. Single-agent mode skips reviewer and empty-review revision calls.
6. Multi-agent mode produces visible configured reviewer calls for every input
   category.
7. The first activity event appears immediately after job acceptance and the
   first real model event is accurate.
8. Existing graph versions and public response contracts remain compatible.
9. Focused regressions and available required checks pass, with unavailable
   checks explicitly documented.
