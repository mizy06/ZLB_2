from __future__ import annotations

import asyncio
import mimetypes
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .config import Settings
from .model_provider import ModelProviderError, OpenAICompatibleClient


_UPLOAD_POLICY_FIELDS = (
    "upload_host",
    "upload_dir",
    "oss_access_key_id",
    "signature",
    "policy",
    "x_oss_object_acl",
    "x_oss_forbid_overwrite",
)


class QwenClient(OpenAICompatibleClient):
    supports_multimodal = True
    supports_responses = True
    supports_temporary_uploads = True

    def __init__(self, settings: Settings):
        super().__init__(
            settings=settings,
            api_key=settings.qwen_api_key,
            base_url=settings.qwen_base_url,
            provider_name="Qwen",
            api_key_env_name="QWEN_API_KEY",
            temperature=settings.qwen_temperature,
        )

    def _temporary_upload_url(self) -> str:
        parts = urlsplit(self.base_url)
        suffix = "/compatible-mode/v1"
        if not parts.path.rstrip("/").endswith(suffix):
            raise ModelProviderError(
                "Qwen endpoint does not support temporary uploads"
            )
        return urlunsplit(
            (
                parts.scheme,
                parts.netloc,
                "/api/v1/uploads",
                "",
                "",
            )
        )

    @staticmethod
    def _validated_upload_policy(payload: Any) -> dict[str, str]:
        if not isinstance(payload, dict):
            raise ModelProviderError("Qwen temporary upload policy is invalid")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ModelProviderError("Qwen temporary upload policy has no data")

        policy: dict[str, str] = {}
        for field in _UPLOAD_POLICY_FIELDS:
            value = data.get(field)
            if not isinstance(value, (str, bool, int)) or not str(value).strip():
                raise ModelProviderError(
                    "Qwen temporary upload policy is incomplete"
                )
            policy[field] = str(value)

        upload_host = urlsplit(policy["upload_host"])
        hostname = (upload_host.hostname or "").casefold()
        if (
            upload_host.scheme.casefold() != "https"
            or not hostname.endswith(".aliyuncs.com")
        ):
            raise ModelProviderError(
                "Qwen temporary upload policy returned an unsafe host"
            )
        return policy

    async def upload_temporary_files(
        self,
        *,
        model: str,
        files: Sequence[tuple[str, Path]],
        concurrency: int = 8,
        timeout_seconds: float = 300,
    ) -> list[tuple[str, str]]:
        if not self.api_key:
            raise ModelProviderError("未配置 QWEN_API_KEY")
        if not files:
            raise ValueError("temporary upload requires at least one file")

        prepared: list[tuple[str, Path]] = []
        labels: set[str] = set()
        for raw_label, raw_path in files:
            label = str(raw_label).strip()
            path = Path(raw_path)
            if not label or label in labels:
                raise ValueError("temporary upload requires unique labels")
            if not path.is_file():
                raise FileNotFoundError(path)
            labels.add(label)
            prepared.append((label, path))

        policy_response = await self._request(
            "get",
            self._temporary_upload_url(),
            model=model,
            operation="temporary_upload_policy",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            params={"action": "getPolicy", "model": model},
            max_attempts=2,
            total_timeout_seconds=min(float(timeout_seconds), 60),
        )
        try:
            policy_payload = policy_response.json()
        except ValueError as exc:
            raise ModelProviderError(
                "Qwen temporary upload policy is not valid JSON"
            ) from exc
        policy = self._validated_upload_policy(policy_payload)
        semaphore = asyncio.Semaphore(max(1, min(int(concurrency), 32)))

        async def upload_one(label: str, path: Path) -> tuple[str, str]:
            key = f"{policy['upload_dir'].rstrip('/')}/{path.name}"
            content_type = (
                mimetypes.guess_type(path.name)[0]
                or "application/octet-stream"
            )
            content = await asyncio.to_thread(path.read_bytes)
            form_data = {
                "OSSAccessKeyId": policy["oss_access_key_id"],
                "Signature": policy["signature"],
                "policy": policy["policy"],
                "key": key,
                "x-oss-object-acl": policy["x_oss_object_acl"],
                "x-oss-forbid-overwrite": policy[
                    "x_oss_forbid_overwrite"
                ],
                "success_action_status": "200",
                "x-oss-content-type": content_type,
            }
            async with semaphore:
                await self._request(
                    "post",
                    policy["upload_host"],
                    model=model,
                    operation="temporary_upload",
                    headers={"Accept": "application/json"},
                    data=form_data,
                    files={
                        "file": (
                            path.name,
                            content,
                            content_type,
                        )
                    },
                    max_attempts=2,
                    total_timeout_seconds=timeout_seconds,
                )
            return label, f"oss://{key}"

        return list(
            await asyncio.gather(
                *(upload_one(label, path) for label, path in prepared)
            )
        )
