# Global-editor PPT vision experiment

This image keeps the existing upload, job, history, export, and frontend
surfaces, but replaces the C+ generation path for PPTX jobs with a
single-writer editorial loop:

1. Render every slide through LibreOffice and Poppler.
2. Compress every rendered slide once and upload it to DashScope temporary OSS.
3. Put the stable `oss://` references, in order, into the first Responses call.
4. Let one global editor read the whole deck and write the complete first tree.
5. Run independent content-omission, precision-pruning, and multilevel
   structural reviews. Only the omission reviewer rereads every slide; the
   other reviewers inspect the editorial brief and current graph.
6. Return blocker and major findings to the same global editor for a bounded
   number of revisions. After the last allowed revision, publish the validated
   graph without a blocking extra review round.
7. Validate the returned tree locally and persist it as a normal graph version.

Reviewers never modify the graph. The global editor is the only writer, and
unchanged nodes retain stable temporary IDs between revisions. The experiment
does not run theme synthesis, branch teams, or the topology solver.

The pipeline intentionally does not calculate slide or content-unit coverage.
An abstractive node can summarize several slides, and administrative or
repeated slides can be deliberately pruned. Important omissions are instead
reported as evidence-backed blocker or major findings.

Rendered slides are reused across owner-scoped runs when the source digest and
render settings match and every cached asset is still present. The first
global-editor Responses call sends every stable image URL once with
`x-dashscope-session-cache: enable`. Later omission reviews, Patch revisions,
Patch repair, and full-rewrite fallback normally send no image or URL at all;
they continue from the preceding stored response through
`previous_response_id`. The global editor and omission reviewer still reason
from the original full-slide images rather than a derived summary.

Response IDs, temporary image URLs, cache-token counts, and chain-reset events
are persisted in private SQLite checkpoints. Public result manifests expose
only aggregate cache and fallback counters, not the response IDs or URLs. If a
stored response cannot be continued, the pipeline uses the same stable URLs to
create a fresh Responses root. If Responses is unavailable, it falls back to
the existing Chat Completions path; stable URLs are still preferred over
Base64 whenever upload already succeeded.

Every later review receives its own historical issues together with the latest
editorial decisions. A historical issue may be returned again only when the
same substantive problem still exists in the current graph. Stable issue IDs,
no-op revision detection, and the bounded revision count prevent wording-only
review churn.

Build and run it by layering the experiment override over the production
Compose file:

```bash
docker compose \
  -f compose.prod.yml \
  -f compose.single-shot-ppt.yml \
  up --build
```

The production Compose file still supplies required tokens, encrypted Qwen
secrets, volumes, and the public port. The experiment accepts PPTX only.

Useful experiment controls:

- `MINDMAP_EDITORIAL_MODEL`: defaults to `QWEN_VISION_MODEL`.
- `MINDMAP_EDITORIAL_RENDER_DPI`: full-slide render DPI, default `120`.
- `MINDMAP_EDITORIAL_IMAGE_MAX_EDGE`: JPEG long-edge cap override, default
  `1280`. The tested Qwen model reported the same visual token count at `1152`,
  so standard mode keeps `1280` for legibility.
- `MINDMAP_EDITORIAL_RESPONSES_ENABLED`: enable stable temporary URLs,
  Responses, `previous_response_id`, and Session Cache; default `true`.
- `MINDMAP_EDITORIAL_UPLOAD_CONCURRENCY`: concurrent temporary OSS uploads
  after one shared upload-policy request, default `8`.
- `MINDMAP_EDITORIAL_MAX_REQUEST_MIB`: fail-before-call payload limit for the
  final inline Base64 fallback only, default `96`. Slides are never silently
  dropped.
- `MINDMAP_EDITORIAL_DRAFT_MAX_OUTPUT_TOKENS`: first-draft answer budget,
  default `14000`; standard mode applies `9000` to the Chat fallback. The
  current Qwen Responses compatibility surface does not expose a documented
  hard output-token parameter, so its primary path relies on the bounded JSON
  schema and role prompt.
- `MINDMAP_EDITORIAL_REVIEW_MAX_OUTPUT_TOKENS`: each reviewer answer budget,
  default `12000`; standard mode caps pruning/structure reviews at `4500` and
  the semantic omission Chat fallback at `3500`.
- `MINDMAP_EDITORIAL_REVISION_MAX_OUTPUT_TOKENS`: editor revision budget,
  default `14000`; this budget applies when the complete-graph safety fallback
  uses Chat Completions.
- `MINDMAP_EDITORIAL_PATCH_REVISIONS`: use transactional incremental Patch
  revisions, default `true` in the editorial Compose overlay. The editor still
  receives the original affected slide images rather than a source summary.
- `MINDMAP_EDITORIAL_PATCH_MAX_OUTPUT_TOKENS`: incremental Patch and one-shot
  Patch and repair Chat fallback budget, default `7000`; standard mode caps it
  at `4500`.
- `MINDMAP_EDITORIAL_MAX_REVISIONS`: maximum accepted revision cycles,
  default `1` in standard mode and `2` in precision mode. Standard mode is
  capped at one revision even when a larger legacy global value is supplied.
- `MINDMAP_EDITORIAL_THINKING_BUDGET`: draft/full-rewrite reasoning budget,
  default `1536` in standard mode and `4096` in precision mode. Responses maps
  this legacy numeric control to `reasoning.effort`.
- `MINDMAP_EDITORIAL_REVIEW_THINKING_BUDGET`: reviewer reasoning budget,
  default `768` in standard mode and `2048` in precision mode.
- `MINDMAP_EDITORIAL_CONTENT_REVIEW_THINKING_BUDGET`: semantic omission
  reviewer reasoning budget, default `512` in standard mode and `2048` in
  precision mode.
- `MINDMAP_EDITORIAL_PATCH_THINKING_BUDGET`: Patch and Patch-repair reasoning
  budget, default `768` in standard mode and `2048` in precision mode.
- `MINDMAP_EDITORIAL_FULL_REWRITE_FALLBACK`: override complete-graph fallback
  after Patch plus repair fail. The mode default is disabled for standard and
  enabled for precision.
- `MINDMAP_EDITORIAL_MAX_DEPTH`: maximum tree depth, default `6`.
- `MINDMAP_EDITORIAL_TIMEOUT_SECONDS`: per-request timeout, default `300`.

The publish/quality gate passes when the latest review/revision decisions leave
no unresolved blocker or major findings and every required reviewer completed
successfully.

When Patch revisions are enabled, each revision is applied transactionally.
Unknown targets, duplicate IDs, cycles, invalid slide references, excessive
depth, and non-leaf deletion reject the entire Patch. Harmless no-effect
update, move, or position operations are skipped and recorded; accepted
decisions still require a real deterministic graph effect. The editor receives
one repair attempt with the deterministic error and the unchanged current
graph. If repair still fails, standard mode preserves the previous valid graph,
while precision mode may use the complete-graph fallback. No slide or content
coverage calculator is introduced; important omissions remain a semantic
reviewer responsibility.

The draft request is the only normal Responses request that contains image
references. The semantic omission reviewer continues from the draft response,
and each accepted editor response becomes the parent of the next visual role.
The provider usage is recorded from
`usage.input_tokens_details.cached_tokens`; `responses_cache_hit_count`,
`responses_cached_tokens_total`, chain length, chain resets, and Chat fallback
counts are included in the final manifest for operational verification.
