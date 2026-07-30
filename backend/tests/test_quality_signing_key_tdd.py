from __future__ import annotations

import base64
import hashlib
import json
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PublicKey,
)

from backend.tools.quality_signing_key import (
    QualitySigningKeyError,
    generate_quality_signing_key,
)
from backend.tools.pdf_page_knowledge_evaluator import (
    sign_evaluation_artifact_with_age_key,
)


class QualitySigningKeyTDDTests(unittest.TestCase):
    @unittest.skipUnless(
        shutil.which("age") and shutil.which("age-keygen"),
        "age and age-keygen are required for the real round trip",
    )
    def test_real_age_round_trip_signs_with_generated_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            identity_path = root / "age-identity.txt"
            encrypted_path = root / "quality-private.pem.age"
            public_key_path = root / "quality-public.pem"
            trust_record_path = root / "quality-trust.json"
            evaluation_path = root / "evaluation.json"
            signature_path = root / "evaluation.sig.json"
            keygen = subprocess.run(
                [
                    str(shutil.which("age-keygen")),
                    "-o",
                    str(identity_path),
                ],
                capture_output=True,
                check=False,
                timeout=20,
            )
            self.assertEqual(keygen.returncode, 0)
            recipient_result = subprocess.run(
                [
                    str(shutil.which("age-keygen")),
                    "-y",
                    str(identity_path),
                ],
                capture_output=True,
                check=False,
                timeout=20,
            )
            self.assertEqual(recipient_result.returncode, 0)
            recipient = recipient_result.stdout.decode("ascii").strip()

            trust_record = generate_quality_signing_key(
                age_recipient=recipient,
                encrypted_private_key_path=encrypted_path,
                public_key_path=public_key_path,
                trust_record_path=trust_record_path,
            )
            evaluation_path.write_text(
                '{"schema_version":"test","passed":true}',
                encoding="utf-8",
            )
            signature = sign_evaluation_artifact_with_age_key(
                evaluation_path=evaluation_path,
                encrypted_private_key_path=encrypted_path,
                age_identity_path=identity_path,
                signature_path=signature_path,
            )

            public_key = serialization.load_pem_public_key(
                public_key_path.read_bytes()
            )
            self.assertIsInstance(public_key, Ed25519PublicKey)
            public_key.verify(
                base64.b64decode(signature["signature_base64"]),
                evaluation_path.read_bytes(),
            )
            self.assertEqual(
                signature["public_key_sha256"],
                trust_record["public_key_sha256"],
            )

    def test_ceremony_encrypts_private_key_and_writes_public_trust_record(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            age_path = root / "age"
            encrypted_path = root / "quality-private.pem.age"
            public_key_path = root / "quality-public.pem"
            trust_record_path = root / "quality-trust.json"
            age_path.write_text("test executable", encoding="utf-8")
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=b"age-encrypted-ed25519-private-key",
                stderr=b"",
            )
            captured_private_key: list[bytes] = []

            def encrypt(*args, **kwargs):
                captured_private_key.append(bytes(kwargs["input"]))
                return completed

            with (
                patch(
                    "backend.tools.quality_signing_key."
                    "_find_age_executable",
                    return_value=age_path,
                ),
                patch(
                    "backend.tools.quality_signing_key.subprocess.run",
                    side_effect=encrypt,
                ) as run,
            ):
                trust_record = generate_quality_signing_key(
                    age_recipient="age1testrecipient",
                    encrypted_private_key_path=encrypted_path,
                    public_key_path=public_key_path,
                    trust_record_path=trust_record_path,
                )

            call = run.call_args
            self.assertEqual(
                call.args[0],
                [
                    str(age_path.resolve()),
                    "--encrypt",
                    "-r",
                    "age1testrecipient",
                ],
            )
            self.assertIn(
                b"-----BEGIN PRIVATE KEY-----",
                captured_private_key[0],
            )
            self.assertEqual(
                set(call.kwargs["input"]),
                {0},
            )
            self.assertNotIn(
                b"-----BEGIN PRIVATE KEY-----",
                encrypted_path.read_bytes(),
            )
            self.assertEqual(
                encrypted_path.read_bytes(),
                b"age-encrypted-ed25519-private-key",
            )
            public_key = serialization.load_pem_public_key(
                public_key_path.read_bytes()
            )
            self.assertIsInstance(public_key, Ed25519PublicKey)
            public_key_der = public_key.public_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            self.assertEqual(
                trust_record["public_key_sha256"],
                hashlib.sha256(public_key_der).hexdigest(),
            )
            self.assertEqual(
                trust_record["encrypted_private_key_sha256"],
                hashlib.sha256(encrypted_path.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                json.loads(trust_record_path.read_text(encoding="utf-8")),
                trust_record,
            )
            self.assertNotIn(
                "PRIVATE KEY",
                trust_record_path.read_text(encoding="utf-8"),
            )
            self.assertEqual(
                stat.S_IMODE(encrypted_path.stat().st_mode),
                0o600,
            )
            self.assertEqual(
                stat.S_IMODE(public_key_path.stat().st_mode),
                0o644,
            )
            self.assertEqual(
                stat.S_IMODE(trust_record_path.stat().st_mode),
                0o644,
            )

    def test_ceremony_refuses_overwrite_before_generating_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            encrypted_path = root / "quality-private.pem.age"
            encrypted_path.write_bytes(b"existing")

            with patch(
                "backend.tools.quality_signing_key.Ed25519PrivateKey.generate"
            ) as generate:
                with self.assertRaisesRegex(
                    QualitySigningKeyError,
                    "output already exists",
                ):
                    generate_quality_signing_key(
                        age_recipient="age1testrecipient",
                        encrypted_private_key_path=encrypted_path,
                        public_key_path=root / "quality-public.pem",
                        trust_record_path=root / "quality-trust.json",
                    )

            generate.assert_not_called()
            self.assertEqual(encrypted_path.read_bytes(), b"existing")

    def test_ceremony_does_not_delete_concurrently_created_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            age_path = root / "age"
            encrypted_path = root / "quality-private.pem.age"
            public_key_path = root / "quality-public.pem"
            trust_record_path = root / "quality-trust.json"
            age_path.write_text("test executable", encoding="utf-8")
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=b"age-encrypted-ed25519-private-key",
                stderr=b"",
            )

            def collide(path, flags, mode):
                del flags, mode
                Path(path).write_bytes(b"concurrent-owner")
                raise FileExistsError

            with (
                patch(
                    "backend.tools.quality_signing_key."
                    "_find_age_executable",
                    return_value=age_path,
                ),
                patch(
                    "backend.tools.quality_signing_key.subprocess.run",
                    return_value=completed,
                ),
                patch(
                    "backend.tools.quality_signing_key.os.open",
                    side_effect=collide,
                ),
            ):
                with self.assertRaisesRegex(
                    QualitySigningKeyError,
                    "output could not be written",
                ):
                    generate_quality_signing_key(
                        age_recipient="age1testrecipient",
                        encrypted_private_key_path=encrypted_path,
                        public_key_path=public_key_path,
                        trust_record_path=trust_record_path,
                    )

            self.assertEqual(
                encrypted_path.read_bytes(),
                b"concurrent-owner",
            )
            self.assertFalse(public_key_path.exists())
            self.assertFalse(trust_record_path.exists())

    def test_ceremony_failures_are_bounded_sanitized_and_leave_no_outputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            age_path = root / "age"
            age_path.write_text("test executable", encoding="utf-8")

            def paths(prefix: str) -> tuple[Path, Path, Path]:
                return (
                    root / f"{prefix}-private.pem.age",
                    root / f"{prefix}-public.pem",
                    root / f"{prefix}-trust.json",
                )

            missing_age_outputs = paths("missing-age")
            with patch(
                "backend.tools.quality_signing_key."
                "_find_age_executable",
                return_value=None,
            ):
                with self.assertRaisesRegex(
                    QualitySigningKeyError,
                    "age executable is unavailable",
                ):
                    generate_quality_signing_key(
                        age_recipient="age1testrecipient",
                        encrypted_private_key_path=missing_age_outputs[0],
                        public_key_path=missing_age_outputs[1],
                        trust_record_path=missing_age_outputs[2],
                    )
            self.assertFalse(any(path.exists() for path in missing_age_outputs))

            timeout_outputs = paths("timeout")
            with (
                patch(
                    "backend.tools.quality_signing_key."
                    "_find_age_executable",
                    return_value=age_path,
                ),
                patch(
                    "backend.tools.quality_signing_key.subprocess.run",
                    side_effect=subprocess.TimeoutExpired(
                        cmd=["age"],
                        timeout=20,
                    ),
                ),
            ):
                with self.assertRaisesRegex(
                    QualitySigningKeyError,
                    "age encryption timed out",
                ):
                    generate_quality_signing_key(
                        age_recipient="age1testrecipient",
                        encrypted_private_key_path=timeout_outputs[0],
                        public_key_path=timeout_outputs[1],
                        trust_record_path=timeout_outputs[2],
                    )
            self.assertFalse(any(path.exists() for path in timeout_outputs))

            leaked_key = "PRIVATE-KEY-MATERIAL-MUST-NOT-APPEAR"
            failed_outputs = paths("failed")
            failed = subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout=b"",
                stderr=leaked_key.encode("utf-8"),
            )
            with (
                patch(
                    "backend.tools.quality_signing_key."
                    "_find_age_executable",
                    return_value=age_path,
                ),
                patch(
                    "backend.tools.quality_signing_key.subprocess.run",
                    return_value=failed,
                ),
            ):
                with self.assertRaises(QualitySigningKeyError) as raised:
                    generate_quality_signing_key(
                        age_recipient="age1testrecipient",
                        encrypted_private_key_path=failed_outputs[0],
                        public_key_path=failed_outputs[1],
                        trust_record_path=failed_outputs[2],
                    )
            self.assertIn("age encryption failed", str(raised.exception))
            self.assertNotIn(leaked_key, str(raised.exception))
            self.assertFalse(any(path.exists() for path in failed_outputs))

            oversized_outputs = paths("oversized")
            oversized = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=b"x" * 65_537,
                stderr=b"",
            )
            with (
                patch(
                    "backend.tools.quality_signing_key."
                    "_find_age_executable",
                    return_value=age_path,
                ),
                patch(
                    "backend.tools.quality_signing_key.subprocess.run",
                    return_value=oversized,
                ),
            ):
                with self.assertRaisesRegex(
                    QualitySigningKeyError,
                    "encrypted private key is too large",
                ):
                    generate_quality_signing_key(
                        age_recipient="age1testrecipient",
                        encrypted_private_key_path=oversized_outputs[0],
                        public_key_path=oversized_outputs[1],
                        trust_record_path=oversized_outputs[2],
                    )
            self.assertFalse(any(path.exists() for path in oversized_outputs))

            with self.assertRaisesRegex(
                QualitySigningKeyError,
                "age recipient is required",
            ):
                generate_quality_signing_key(
                    age_recipient=" ",
                    encrypted_private_key_path=root / "blank-private.pem.age",
                    public_key_path=root / "blank-public.pem",
                    trust_record_path=root / "blank-trust.json",
                )


if __name__ == "__main__":
    unittest.main()
