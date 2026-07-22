from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.kimi_provider import KimiClient
from backend.app.config import Settings, _load_kimi_secret, _parse_env_text


def settings(api_key: str = "test-key") -> Settings:
    return Settings(
        kimi_api_key=api_key,
        kimi_base_url="https://api.moonshot.cn/v1",
        kimi_model="kimi-k3",
        kimi_reasoning_effort="low",
        kimi_secret_source="test",
        kimi_secret_error="",
        workspace_name="test",
        workspace_id="",
        vision_max_pages=24,
        external_engine_token="",
        asset_public_base_url="",
        asset_access_token="",
        mindmap_data_dir=Path("."),
        blackboard_path=Path("blackboard.sqlite3"),
    )


class KimiConfigTests(unittest.TestCase):
    def test_parse_env_text_accepts_export_and_quotes(self):
        values = _parse_env_text(
            "# encrypted payload\nexport KIMI_API_KEY='secret-value'\n"
        )
        self.assertEqual(values["KIMI_API_KEY"], "secret-value")

    def test_age_decryption_sets_process_environment(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            age = root / "age.exe"
            identity = root / "identity.txt"
            ciphertext = root / "kimi.age"
            for path in (age, identity, ciphertext):
                path.write_bytes(b"placeholder")

            completed = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=b"KIMI_API_KEY=decrypted-test-key\n",
                stderr=b"",
            )
            environment = {
                "KIMI_API_KEY": "",
                "MOONSHOT_API_KEY": "",
                "AGE_EXECUTABLE": str(age),
                "KIMI_AGE_IDENTITY_FILE": str(identity),
                "KIMI_SECRETS_FILE": str(ciphertext),
            }
            with (
                patch.dict(os.environ, environment, clear=False),
                patch("backend.app.config.subprocess.run", return_value=completed),
            ):
                key, source, error = _load_kimi_secret()
                self.assertEqual(key, "decrypted-test-key")
                self.assertEqual(os.environ["KIMI_API_KEY"], key)
                self.assertEqual(source, "age")
                self.assertEqual(error, "")

    def test_k3_payload_uses_reasoning_without_temperature(self):
        client = KimiClient(settings())
        payload = client._chat_payload(
            model="kimi-k3",
            messages=[{"role": "user", "content": "test"}],
            max_tokens=512,
            json_mode=True,
        )
        self.assertEqual(payload["model"], "kimi-k3")
        self.assertEqual(payload["reasoning_effort"], "low")
        self.assertEqual(payload["max_completion_tokens"], 512)
        self.assertNotIn("temperature", payload)
        self.assertNotIn("max_tokens", payload)


if __name__ == "__main__":
    unittest.main()
