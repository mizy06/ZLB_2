from __future__ import annotations

import contextlib
import io
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.secret_preflight import (
    SecretPreflightError,
    main,
    validate_secret_file,
)


def fake_stat(*, mode: int, uid: int = 0, gid: int = 10001) -> os.stat_result:
    return os.stat_result(
        (
            stat.S_IFREG | mode,
            1,
            1,
            1,
            uid,
            gid,
            64,
            0,
            0,
            0,
        )
    )


class SecretPreflightValidationTDDTests(unittest.TestCase):
    def test_missing_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing.age"
            with self.assertRaisesRegex(SecretPreflightError, "不存在"):
                validate_secret_file(missing)

    def test_symlink_is_rejected_even_when_target_is_regular(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "identity.txt"
            target.write_text("AGE-SECRET-KEY-DO-NOT-LOG", encoding="utf-8")
            link = root / "identity-link.txt"
            link.symlink_to(target)

            with self.assertRaisesRegex(SecretPreflightError, "符号链接"):
                validate_secret_file(link)

    def test_world_readable_file_is_rejected(self):
        path = Path("/run/secrets/qwen.enc.env.age")
        with patch(
            "backend.app.secret_preflight.os.lstat",
            return_value=fake_stat(mode=0o444),
        ):
            with self.assertRaisesRegex(SecretPreflightError, "0440"):
                validate_secret_file(path)

    def test_wrong_group_is_rejected(self):
        path = Path("/run/secrets/qwen.enc.env.age")
        with patch(
            "backend.app.secret_preflight.os.lstat",
            return_value=fake_stat(mode=0o440, gid=0),
        ):
            with self.assertRaisesRegex(SecretPreflightError, "GID 10001"):
                validate_secret_file(path)

    def test_group_unreadable_file_is_rejected(self):
        path = Path("/run/secrets/qwen.enc.env.age")
        with patch(
            "backend.app.secret_preflight.os.lstat",
            return_value=fake_stat(mode=0o400),
        ):
            with self.assertRaisesRegex(SecretPreflightError, "0440"):
                validate_secret_file(path)

    def test_root_group_10001_mode_0440_passes(self):
        path = Path("/run/secrets/qwen.enc.env.age")
        with patch(
            "backend.app.secret_preflight.os.lstat",
            return_value=fake_stat(mode=0o440),
        ):
            validate_secret_file(path)

    def test_non_regular_file_is_rejected(self):
        path = Path("/run/secrets/qwen.enc.env.age")
        directory_stat = os.stat_result(
            (
                stat.S_IFDIR | 0o440,
                1,
                1,
                1,
                0,
                10001,
                0,
                0,
                0,
                0,
            )
        )
        with patch(
            "backend.app.secret_preflight.os.lstat",
            return_value=directory_stat,
        ):
            with self.assertRaisesRegex(SecretPreflightError, "普通文件"):
                validate_secret_file(path)


class SecretPreflightCLITDDTests(unittest.TestCase):
    def test_error_output_never_contains_secret_contents(self):
        secret_text = "QWEN_API_KEY=must-never-appear-in-preflight-output"
        with tempfile.TemporaryDirectory() as temp_dir:
            secret = Path(temp_dir) / "qwen.enc.env.age"
            secret.write_text(secret_text, encoding="utf-8")
            secret.chmod(0o444)
            stderr = io.StringIO()

            with contextlib.redirect_stderr(stderr):
                exit_code = main(
                    [
                        "--expected-uid",
                        str(os.getuid()),
                        "--expected-gid",
                        str(os.getgid()),
                        "--expected-mode",
                        "0440",
                        str(secret),
                    ]
                )

        self.assertEqual(exit_code, 2)
        self.assertNotIn(secret_text, stderr.getvalue())
        self.assertNotIn("must-never-appear", stderr.getvalue())

    def test_successful_cli_hands_off_to_requested_process(self):
        secret = Path("/run/secrets/qwen.enc.env.age")
        with (
            patch(
                "backend.app.secret_preflight.os.lstat",
                return_value=fake_stat(mode=0o440),
            ),
            patch("backend.app.secret_preflight.os.execvp") as execvp,
        ):
            exit_code = main(
                [
                    str(secret),
                    "--exec",
                    "python",
                    "-m",
                    "uvicorn",
                    "backend.app.main:app",
                ]
            )

        self.assertEqual(exit_code, 0)
        execvp.assert_called_once_with(
            "python",
            [
                "python",
                "-m",
                "uvicorn",
                "backend.app.main:app",
            ],
        )


class ComposeSecretPreflightTDDTests(unittest.TestCase):
    def test_production_compose_runs_preflight_without_fake_mode(self):
        compose = (
            Path(__file__).resolve().parents[2] / "compose.prod.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("backend.app.secret_preflight", compose)
        self.assertIn("/run/secrets/qwen-age-identity.txt", compose)
        self.assertIn("/run/secrets/qwen.enc.env.age", compose)
        self.assertNotIn("mode: 0444", compose)

    def test_production_compose_uses_public_workbench_owner(self):
        compose = (
            Path(__file__).resolve().parents[2] / "compose.prod.yml"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "MINDMAP_WORKBENCH_OWNER_ID: "
            "${MINDMAP_WORKBENCH_OWNER_ID:-public-workbench}",
            compose,
        )
        self.assertNotIn("MINDMAP_API_TOKEN", compose)
        self.assertNotIn("MINDMAP_SESSION_COOKIE", compose)

    def test_production_compose_allows_three_page_level_attempts(self):
        compose = (
            Path(__file__).resolve().parents[2] / "compose.prod.yml"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "MINDMAP_PDF_TRANSCRIPTION_MAX_ATTEMPTS: "
            "${MINDMAP_PDF_TRANSCRIPTION_MAX_ATTEMPTS:-3}",
            compose,
        )

    def test_production_compose_forces_direct_visual_extraction(self):
        compose = (
            Path(__file__).resolve().parents[2] / "compose.prod.yml"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "MINDMAP_PDF_PAGE_EXTRACTION_MODE: direct",
            compose,
        )
        self.assertIn(
            "MINDMAP_PDF_TRANSCRIPTION_MODE: vision_nodes_strict",
            compose,
        )

    def test_production_compose_defaults_and_allows_qwen_profile_override(self):
        compose = (
            Path(__file__).resolve().parents[2] / "compose.prod.yml"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "MINDMAP_QWEN_PRODUCTION_PROFILE: "
            "${MINDMAP_QWEN_PRODUCTION_PROFILE:-standard}",
            compose,
        )


class ProductionDeploymentContractTDDTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[2]
        cls.root = root
        cls.compose = (root / "compose.prod.yml").read_text(encoding="utf-8")
        cls.dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
        cls.requirements = (
            root / "backend" / "requirements.txt"
        ).read_text(encoding="utf-8")

    def test_host_port_is_parameterized_and_loopback_safe_by_default(self):
        self.assertIn(
            "container_name: ${MINDMAP_CONTAINER_NAME:-zlb-mindmap}",
            self.compose,
        )
        self.assertIn(
            '"${MINDMAP_BIND_HOST:-127.0.0.1}:'
            '${MINDMAP_PUBLIC_PORT:-5173}:8000"',
            self.compose,
        )

    def test_persistent_volume_names_and_external_mode_are_parameterized(self):
        self.assertIn(
            "name: ${MINDMAP_DATA_VOLUME_NAME:-zlb-mindmap-data}",
            self.compose,
        )
        self.assertIn(
            "external: ${MINDMAP_DATA_VOLUME_EXTERNAL:-false}",
            self.compose,
        )
        self.assertIn(
            "name: ${MINDMAP_UPLOADS_VOLUME_NAME:-zlb-mindmap-uploads}",
            self.compose,
        )
        self.assertIn(
            "external: ${MINDMAP_UPLOADS_VOLUME_EXTERNAL:-false}",
            self.compose,
        )

    def test_host_secret_sources_are_parameterized(self):
        self.assertIn(
            "file: ${QWEN_AGE_IDENTITY_SOURCE_FILE:-"
            "./runtime/secrets/qwen-age-identity.txt}",
            self.compose,
        )
        self.assertIn(
            "file: ${QWEN_ENCRYPTED_ENV_SOURCE_FILE:-"
            "./runtime/secrets/qwen.enc.env.age}",
            self.compose,
        )

    def test_production_resource_and_shutdown_defaults_are_bounded(self):
        self.assertIn("stop_grace_period: 60s", self.compose)
        self.assertIn(
            "mem_limit: ${MINDMAP_MEMORY_LIMIT:-3g}",
            self.compose,
        )

    def test_production_requires_validated_image_identity(self):
        self.assertIn(
            "image: ${MINDMAP_IMAGE_REF:?MINDMAP_IMAGE_REF is required}",
            self.compose,
        )
        self.assertIn(
            "IMAGE_DIGEST: ${IMAGE_DIGEST:?IMAGE_DIGEST is required}",
            self.compose,
        )

    def test_provider_defaults_match_single_attempt_ninety_second_budget(self):
        self.assertIn(
            "MINDMAP_PROVIDER_TIMEOUT_SECONDS: "
            "${MINDMAP_PROVIDER_TIMEOUT_SECONDS:-90}",
            self.compose,
        )
        self.assertIn(
            "MINDMAP_PROVIDER_MAX_ATTEMPTS: "
            "${MINDMAP_PROVIDER_MAX_ATTEMPTS:-1}",
            self.compose,
        )

    def test_git_sha_metadata_does_not_invalidate_dependency_layers(self):
        dependency_layer = self.dockerfile.index(
            "RUN python -m pip install -r /app/backend/requirements.txt"
        )
        git_sha_arg = self.dockerfile.index("ARG GIT_SHA=unknown")
        git_sha_env = self.dockerfile.index("ENV GIT_SHA=${GIT_SHA}")
        backend_copy = self.dockerfile.index(
            "COPY --chown=10001:10001 backend /app/backend"
        )

        self.assertLess(dependency_layer, git_sha_arg)
        self.assertLess(git_sha_arg, git_sha_env)
        self.assertLess(git_sha_env, backend_copy)
        self.assertIn(
            "org.opencontainers.image.revision=${GIT_SHA}",
            self.dockerfile,
        )

    def test_base_images_and_system_packages_are_exactly_pinned(self):
        self.assertIn(
            "FROM node:22-bookworm-slim@sha256:"
            "6c74791e557ce11fc957704f6d4fe134a7bc8d6f5ca4403205b2966bd488f6b3",
            self.dockerfile,
        )
        self.assertIn(
            "FROM python:3.12-slim@sha256:"
            "57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de",
            self.dockerfile,
        )
        for package in (
            "age=1.2.1-1+b5",
            "fonts-noto-cjk=1:20240730+repack1-1",
            "libreoffice-impress=4:25.2.3-2+deb13u6",
            "libreoffice-writer=4:25.2.3-2+deb13u6",
            "poppler-utils=25.03.0-5+deb13u4",
        ):
            with self.subTest(package=package):
                self.assertIn(package, self.dockerfile)

    def test_direct_python_requirements_are_exactly_pinned(self):
        requirements = [
            line.strip()
            for line in self.requirements.splitlines()
            if line.strip()
            and not line.lstrip().startswith(("#", "-"))
        ]

        self.assertTrue(requirements)
        self.assertTrue(
            all(
                "==" in requirement
                and ">=" not in requirement
                and "<=" not in requirement
                and "~=" not in requirement
                for requirement in requirements
            )
        )
        self.assertIn("pypdf==6.14.2", requirements)

    def test_transitive_python_dependencies_use_a_complete_constraints_lock(self):
        constraints_path = self.root / "backend" / "constraints.txt"

        self.assertTrue(constraints_path.is_file())
        constraints = [
            line.strip()
            for line in constraints_path.read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertGreaterEqual(len(constraints), 50)
        self.assertTrue(
            all(
                "==" in requirement
                and ">=" not in requirement
                and "<=" not in requirement
                and "~=" not in requirement
                for requirement in constraints
            )
        )
        self.assertIn("-c constraints.txt", self.requirements)
        self.assertIn("langchain-core==1.5.1", constraints)
        self.assertIn("numpy==2.5.1", constraints)
        self.assertIn("websockets==15.0.1", constraints)
        self.assertIn(
            "backend/constraints.txt /app/backend/constraints.txt",
            self.dockerfile,
        )


if __name__ == "__main__":
    unittest.main()
