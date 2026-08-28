from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from backend.vnext.api import ShadowAPISettings, create_shadow_app


VALID_SOURCE = (
    "# Carbonyl Chemistry\n"
    "## Foundations\n"
    "Aldehydes are terminal carbonyl compounds.\n"
    "## Applications\n"
    "Ketones are used in synthesis.\n"
)


def _settings(
    root: Path,
    *,
    enabled: bool = True,
) -> ShadowAPISettings:
    return ShadowAPISettings(
        enabled=enabled,
        service_token="shadow-secret" if enabled else "",
        ingest_root=root / "ingest",
        artifact_root=root / "artifacts",
        control_db=root / "control.sqlite3",
        worker_id="test-shadow-worker",
        max_source_bytes=1024 * 1024,
    )


def _headers(owner: str = "owner-a") -> dict[str, str]:
    return {
        "Authorization": "Bearer shadow-secret",
        "X-VNext-Owner": owner,
    }


class VNextShadowAPITests(unittest.TestCase):
    def test_default_locked_service_has_no_runtime_side_effects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = _settings(root, enabled=False)
            client = TestClient(create_shadow_app(settings))

            health = client.get("/healthz")
            denied = client.post(
                "/v1/shadow/runs",
                json={"source_path": "course.md"},
            )

            self.assertEqual(health.status_code, 200)
            self.assertFalse(health.json()["enabled"])
            self.assertEqual(health.json()["publication"], "disabled")
            self.assertEqual(denied.status_code, 503)
            self.assertFalse(settings.control_db.exists())
            self.assertFalse(settings.artifact_root.exists())

    def test_auth_and_path_confinement_are_mandatory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ingest = root / "ingest"
            ingest.mkdir()
            (root / "outside.md").write_text(
                VALID_SOURCE,
                encoding="utf-8",
            )
            client = TestClient(create_shadow_app(_settings(root)))

            missing = client.post(
                "/v1/shadow/runs",
                json={"source_path": "course.md"},
            )
            wrong = client.post(
                "/v1/shadow/runs",
                json={"source_path": "course.md"},
                headers={
                    "Authorization": "Bearer wrong",
                    "X-VNext-Owner": "owner-a",
                },
            )
            traversal = client.post(
                "/v1/shadow/runs",
                json={"source_path": "../outside.md"},
                headers=_headers(),
            )
            absolute = client.post(
                "/v1/shadow/runs",
                json={"source_path": str(root / "outside.md")},
                headers=_headers(),
            )

            self.assertEqual(missing.status_code, 401)
            self.assertEqual(wrong.status_code, 401)
            self.assertEqual(traversal.status_code, 400)
            self.assertEqual(
                traversal.json()["detail"],
                "source_path_outside_ingest_root",
            )
            self.assertEqual(absolute.status_code, 400)

    def test_run_and_artifact_reads_are_owner_scoped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ingest = root / "ingest"
            ingest.mkdir()
            (ingest / "course.md").write_text(
                VALID_SOURCE,
                encoding="utf-8",
            )
            client = TestClient(create_shadow_app(_settings(root)))
            run_id = f"run_{'7' * 32}"

            created = client.post(
                "/v1/shadow/runs",
                json={
                    "source_path": "course.md",
                    "run_id": run_id,
                },
                headers=_headers(),
            )

            self.assertEqual(created.status_code, 201, created.text)
            payload = created.json()
            self.assertEqual(
                payload["run_manifest"]["execution_status"],
                "succeeded",
            )
            self.assertEqual(
                payload["run_manifest"]["quality_status"],
                "passed",
            )
            self.assertEqual(
                payload["run_manifest"]["publication_status"],
                "draft",
            )
            manifest = client.get(
                f"/v1/shadow/runs/{run_id}",
                headers=_headers(),
            )
            self.assertEqual(manifest.status_code, 200)
            projection_id = payload["projection_artifact_id"]
            artifact = client.get(
                f"/v1/shadow/artifacts/{projection_id}",
                headers=_headers(),
            )
            self.assertEqual(artifact.status_code, 200)
            self.assertEqual(
                artifact.json()["envelope"]["artifact_id"],
                projection_id,
            )
            self.assertEqual(
                artifact.json()["payload"]["quality_status"],
                "passed",
            )
            self.assertEqual(
                client.get(
                    f"/v1/shadow/runs/{run_id}",
                    headers=_headers("owner-b"),
                ).status_code,
                403,
            )
            self.assertEqual(
                client.get(
                    f"/v1/shadow/artifacts/{projection_id}",
                    headers=_headers("owner-b"),
                ).status_code,
                403,
            )
            self.assertEqual(
                client.app.state.security_events[-1]["code"],
                "owner_header_mismatch",
            )

    def test_principal_audience_scope_and_cross_owner_probes_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ingest = root / "ingest"
            ingest.mkdir()
            (ingest / "course.md").write_text(
                VALID_SOURCE,
                encoding="utf-8",
            )
            base = _settings(root)
            audience_client = TestClient(
                create_shadow_app(
                    replace(
                        base,
                        principal_audience="wrong-audience",
                    )
                )
            )
            scope_client = TestClient(
                create_shadow_app(
                    replace(
                        base,
                        principal_scopes=("vnext:read",),
                    )
                )
            )
            self.assertEqual(
                audience_client.post(
                    "/v1/shadow/runs",
                    json={"source_path": "course.md"},
                    headers=_headers(),
                ).status_code,
                403,
            )
            self.assertEqual(
                scope_client.post(
                    "/v1/shadow/runs",
                    json={"source_path": "course.md"},
                    headers=_headers(),
                ).status_code,
                403,
            )

            owner_b_app = create_shadow_app(
                replace(base, principal_owner_id="owner-b")
            )
            owner_b = TestClient(owner_b_app)
            run_id = f"run_{'8' * 32}"
            created = owner_b.post(
                "/v1/shadow/runs",
                json={"source_path": "course.md", "run_id": run_id},
                headers=_headers("owner-b"),
            )
            self.assertEqual(created.status_code, 201, created.text)
            artifact_id = created.json()["projection_artifact_id"]

            owner_a_app = create_shadow_app(base)
            owner_a = TestClient(owner_a_app)
            self.assertEqual(
                owner_a.get(
                    f"/v1/shadow/runs/{run_id}",
                    headers=_headers(),
                ).status_code,
                404,
            )
            self.assertEqual(
                owner_a_app.state.security_events[-1]["code"],
                "run_cross_owner_probe",
            )
            self.assertEqual(
                owner_a.get(
                    f"/v1/shadow/artifacts/{artifact_id}",
                    headers=_headers(),
                ).status_code,
                404,
            )
            self.assertEqual(
                owner_a_app.state.security_events[-1]["code"],
                "artifact_cross_owner_probe",
            )

    def test_shadow_openapi_exposes_no_publish_or_legacy_routes(self):
        with tempfile.TemporaryDirectory() as tmp:
            application = create_shadow_app(_settings(Path(tmp)))
            paths = set(application.openapi()["paths"])

            self.assertEqual(
                paths,
                {
                    "/healthz",
                    "/v1/shadow/runs",
                    "/v1/shadow/runs/{run_id}",
                    "/v1/shadow/artifacts/{artifact_id}",
                },
            )
            self.assertFalse(
                any("publish" in path for path in paths)
            )
            self.assertFalse(any(path.startswith("/api/") for path in paths))


if __name__ == "__main__":
    unittest.main()
