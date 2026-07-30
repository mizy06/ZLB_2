from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image
from pypdf import PdfReader

from backend.tests.vnext_test_support import (
    accepted_concept,
    accepted_relation,
    graph,
)
from backend.vnext.artifacts.canonical import payload_digest
from backend.vnext.artifacts.local_store import LocalArtifactStore
from backend.vnext.cli import main
from backend.vnext.contracts.common import ArtifactRef, ArtifactType
from backend.vnext.contracts.graph import (
    CanonicalConcept,
    CanonicalRelation,
)
from backend.vnext.contracts.presentation import (
    PresentationMedium,
    ProjectionMediaBundle,
    RenderedFileKind,
)
from backend.vnext.orchestration.shadow_pipeline import run_shadow_pipeline
from backend.vnext.presentation import (
    PresentationRenderError,
    PresentationRenderStore,
    build_projection_media_bundle,
)
from backend.vnext.projection import build_diagnostic_projection


NOW = datetime(2026, 7, 29, 16, 0, tzinfo=UTC)
FONT_PATH = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
VALID_SOURCE = (
    "# Carbonyl Chemistry\n"
    "## Foundations\n"
    "Aldehydes are terminal carbonyl compounds.\n"
    "## Applications\n"
    "Ketones are used in synthesis.\n"
)


def _projection_ref(projection) -> ArtifactRef:
    return ArtifactRef(
        owner_id="owner-a",
        artifact_id=f"art_{'8' * 32}",
        artifact_type=ArtifactType.DIAGNOSTIC_PROJECTION,
        payload_digest=payload_digest(projection),
    )


def _rendered_source(root: Path):
    source_path = root / "course.md"
    source_path.write_text(VALID_SOURCE, encoding="utf-8")
    artifacts = LocalArtifactStore(root / "artifacts")
    pipeline = run_shadow_pipeline(
        source_path,
        owner_id="owner-a",
        store=artifacts,
    )
    media = build_projection_media_bundle(
        pipeline.canonical_graph,
        pipeline.projection,
        canonical_graph_ref=artifacts.ref(
            pipeline.canonical_graph_envelope
        ),
        projection_ref=artifacts.ref(pipeline.projection_envelope),
        created_at=NOW,
    )
    render_store = PresentationRenderStore(root / "renders")
    rendered = render_store.render(
        pipeline.canonical_graph,
        pipeline.projection,
        media,
        owner_id="owner-a",
        font_path=FONT_PATH,
        created_at=NOW,
    )
    directory = render_store.directory(
        owner_id="owner-a",
        render_bundle_id=rendered.render_bundle_id,
    )
    return pipeline, media, render_store, rendered, directory


def _outline_titles(values) -> tuple[str, ...]:
    titles: list[str] = []
    for value in values:
        if isinstance(value, list):
            titles.extend(_outline_titles(value))
        else:
            titles.append(str(value.title))
    return tuple(titles)


def _large_graph():
    concepts: list[CanonicalConcept] = []
    for index in range(40):
        template = accepted_concept("1", f"Concept {index}")
        payload = template.model_dump(mode="json")
        payload.update(
            {
                "concept_id": f"concept_{index + 1:032x}",
                "canonical_name": (
                    "Course" if index == 0 else f"Concept {index}"
                ),
                "source_claim_ids": (f"claim_{index + 1:032x}",),
            }
        )
        concepts.append(CanonicalConcept.model_validate(payload))

    relation_pairs = [(0, chapter) for chapter in range(1, 5)]
    relation_pairs.extend(
        (1 + ((index - 5) % 4), index)
        for index in range(5, 40)
    )
    relations: list[CanonicalRelation] = []
    for relation_index, (parent_index, child_index) in enumerate(
        relation_pairs,
        start=1,
    ):
        template = accepted_relation("a", "1", "2")
        payload = template.model_dump(mode="json")
        payload.update(
            {
                "relation_id": f"relation_{relation_index:032x}",
                "source_id": concepts[parent_index].concept_id,
                "target_id": concepts[child_index].concept_id,
                "source_claim_ids": (
                    f"claim_{child_index + 1:032x}",
                ),
            }
        )
        relations.append(CanonicalRelation.model_validate(payload))
    return graph(tuple(concepts), tuple(relations))


class VNextPresentationRendererTests(unittest.TestCase):
    def test_renderer_writes_accessible_html_png_pdf_and_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            (
                pipeline,
                media,
                render_store,
                rendered,
                directory,
            ) = _rendered_source(Path(tmp))

            self.assertFalse(rendered.publication_enabled)
            self.assertEqual(
                render_store.load(
                    owner_id="owner-a",
                    render_bundle_id=rendered.render_bundle_id,
                ),
                rendered,
            )
            self.assertEqual(
                [item.kind for item in rendered.files],
                [
                    RenderedFileKind.WEB_HTML,
                    RenderedFileKind.PNG_TILE,
                    RenderedFileKind.PDF,
                    RenderedFileKind.JSON,
                ],
            )

            html_text = (directory / "web" / "index.html").read_text(
                encoding="utf-8"
            )
            self.assertIn('<canvas id="mindmap"', html_text)
            self.assertIn('role="tree"', html_text)
            self.assertIn("ArrowRight", html_text)
            self.assertIn("@media (max-width: 600px)", html_text)
            self.assertIn(
                ".detail p { margin: 4px 0; color: #526173; "
                "overflow-wrap: anywhere; }",
                html_text,
            )
            self.assertIn(media.semantic_fingerprint, html_text)
            for node in media.media[0].nodes:
                self.assertIn(node.label, html_text)

            png_file = next(
                item
                for item in rendered.files
                if item.kind is RenderedFileKind.PNG_TILE
            )
            with Image.open(directory / png_file.relative_path) as image:
                self.assertEqual(
                    image.info["semantic_fingerprint"],
                    media.semantic_fingerprint,
                )
                self.assertEqual(
                    tuple(json.loads(image.info["node_ids"])),
                    png_file.node_ids,
                )
                self.assertEqual(
                    (image.width, image.height),
                    (png_file.pixel_width, png_file.pixel_height),
                )
                self.assertTrue(
                    any(
                        low != high
                        for low, high in image.convert("RGB").getextrema()
                    )
                )

            pdf_file = next(
                item
                for item in rendered.files
                if item.kind is RenderedFileKind.PDF
            )
            reader = PdfReader(directory / pdf_file.relative_path)
            self.assertEqual(len(reader.pages), pdf_file.logical_page_count)
            self.assertEqual(
                reader.metadata["/SemanticFingerprint"],
                media.semantic_fingerprint,
            )
            titles = _outline_titles(reader.outline)
            self.assertIn("Overview", titles)
            self.assertIn("Sources and review", titles)
            self.assertTrue(
                any(page.get("/Annots") for page in reader.pages)
            )

            json_payload = json.loads(
                (directory / "json" / "mind-map.json").read_bytes()
            )
            self.assertEqual(
                json_payload["semantic_fingerprint"],
                media.semantic_fingerprint,
            )
            self.assertEqual(
                json_payload["canonical_graph"]["graph_id"],
                pipeline.canonical_graph.graph_id,
            )
            self.assertEqual(
                json_payload["projection"]["projection_id"],
                pipeline.projection.projection_id,
            )
            self.assertIn("quality_report", json_payload)
            self.assertIn("audit_records", json_payload)

    def test_render_store_detects_tampering_and_is_owner_scoped(self):
        with tempfile.TemporaryDirectory() as tmp:
            (
                _,
                _,
                render_store,
                rendered,
                directory,
            ) = _rendered_source(Path(tmp))
            png = next(
                item
                for item in rendered.files
                if item.kind is RenderedFileKind.PNG_TILE
            )
            with (directory / png.relative_path).open("ab") as handle:
                handle.write(b"tampered")

            with self.assertRaisesRegex(
                PresentationRenderError,
                "size mismatch",
            ):
                render_store.load(
                    owner_id="owner-a",
                    render_bundle_id=rendered.render_bundle_id,
                )
            with self.assertRaises(FileNotFoundError):
                render_store.load(
                    owner_id="owner-b",
                    render_bundle_id=rendered.render_bundle_id,
                )
            with self.assertRaisesRegex(ValueError, "invalid render bundle"):
                render_store.directory(
                    owner_id="owner-a",
                    render_bundle_id="render_bundle_../../escape",
                )

    def test_renderer_rejects_bundle_semantics_changed_after_planning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "course.md"
            source_path.write_text(VALID_SOURCE, encoding="utf-8")
            artifacts = LocalArtifactStore(root / "artifacts")
            pipeline = run_shadow_pipeline(
                source_path,
                owner_id="owner-a",
                store=artifacts,
            )
            media = build_projection_media_bundle(
                pipeline.canonical_graph,
                pipeline.projection,
                canonical_graph_ref=artifacts.ref(
                    pipeline.canonical_graph_envelope
                ),
                projection_ref=artifacts.ref(
                    pipeline.projection_envelope
                ),
                created_at=NOW,
            )
            payload = media.model_dump(mode="json")
            for medium in payload["media"]:
                medium["nodes"][0]["label"] = "Changed after planning"
            tampered = ProjectionMediaBundle.model_validate(payload)

            with self.assertRaisesRegex(
                PresentationRenderError,
                "semantics do not match",
            ):
                PresentationRenderStore(root / "renders").render(
                    pipeline.canonical_graph,
                    pipeline.projection,
                    tampered,
                    owner_id="owner-a",
                    font_path=FONT_PATH,
                    created_at=NOW,
                )

    def test_large_projection_renders_two_complete_png_tiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            canonical = _large_graph()
            canonical_ref = ArtifactRef(
                owner_id="owner-a",
                artifact_id=f"art_{'7' * 32}",
                artifact_type=ArtifactType.CANONICAL_EXPLICIT_GRAPH,
                payload_digest=payload_digest(canonical),
            )
            projection = build_diagnostic_projection(
                canonical,
                canonical_graph_ref=canonical_ref,
                node_budget=48,
            )
            media = build_projection_media_bundle(
                canonical,
                projection,
                canonical_graph_ref=canonical_ref,
                projection_ref=_projection_ref(projection),
                created_at=NOW,
            )
            store = PresentationRenderStore(Path(tmp) / "renders")
            rendered = store.render(
                canonical,
                projection,
                media,
                owner_id="owner-a",
                font_path=FONT_PATH,
                created_at=NOW,
            )
            png_files = [
                item
                for item in rendered.files
                if item.kind is RenderedFileKind.PNG_TILE
            ]

            self.assertEqual(len(png_files), 2)
            self.assertTrue(
                all(len(item.node_ids) <= 32 for item in png_files)
            )
            self.assertEqual(
                {
                    node_id
                    for item in png_files
                    for node_id in item.node_ids
                },
                set(rendered.semantic_node_ids),
            )
            pdf = next(
                item
                for item in rendered.files
                if item.kind is RenderedFileKind.PDF
            )
            self.assertEqual(
                pdf.logical_page_count,
                next(
                    item.page_or_tile_count
                    for item in media.media
                    if item.medium is PresentationMedium.PDF
                ),
            )

    def test_renderer_rejects_a_font_without_required_cjk_glyphs(self):
        canonical = graph((accepted_concept("1", "醛和酮"),), ())
        canonical_ref = ArtifactRef(
            owner_id="owner-a",
            artifact_id=f"art_{'7' * 32}",
            artifact_type=ArtifactType.CANONICAL_EXPLICIT_GRAPH,
            payload_digest=payload_digest(canonical),
        )
        projection = build_diagnostic_projection(
            canonical,
            canonical_graph_ref=canonical_ref,
        )
        media = build_projection_media_bundle(
            canonical,
            projection,
            canonical_graph_ref=canonical_ref,
            projection_ref=_projection_ref(projection),
            created_at=NOW,
        )

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(
                PresentationRenderError,
                "missing required glyphs",
            ):
                PresentationRenderStore(Path(tmp)).render(
                    canonical,
                    projection,
                    media,
                    owner_id="owner-a",
                    font_path=FONT_PATH,
                    created_at=NOW,
                )

    def test_render_shadow_cli_uses_existing_artifacts_without_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "course.md"
            source_path.write_text(VALID_SOURCE, encoding="utf-8")
            artifact_root = root / "artifacts"
            artifacts = LocalArtifactStore(artifact_root)
            pipeline = run_shadow_pipeline(
                source_path,
                owner_id="owner-a",
                store=artifacts,
            )
            output = io.StringIO()

            with redirect_stdout(output):
                return_code = main(
                    [
                        "render-shadow",
                        "--owner",
                        "owner-a",
                        "--artifact-root",
                        str(artifact_root),
                        "--canonical-artifact",
                        pipeline.canonical_graph_envelope.artifact_id,
                        "--projection-artifact",
                        pipeline.projection_envelope.artifact_id,
                        "--output-root",
                        str(root / "renders"),
                        "--font-path",
                        str(FONT_PATH),
                    ]
                )

            payload = json.loads(output.getvalue())
            self.assertEqual(return_code, 0)
            self.assertFalse(payload["publication_enabled"])
            self.assertEqual(
                payload["files"],
                [
                    "web/index.html",
                    "png/tile-0001.png",
                    "pdf/mind-map.pdf",
                    "json/mind-map.json",
                ],
            )
            self.assertTrue(Path(payload["render_directory"]).is_dir())


if __name__ == "__main__":
    unittest.main()
