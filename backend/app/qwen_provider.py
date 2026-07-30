from __future__ import annotations

from .config import Settings
from .model_provider import OpenAICompatibleClient


class QwenClient(OpenAICompatibleClient):
    supports_multimodal = True

    def __init__(self, settings: Settings):
        super().__init__(
            settings=settings,
            api_key=settings.qwen_api_key,
            base_url=settings.qwen_base_url,
            provider_name="Qwen",
            api_key_env_name="QWEN_API_KEY",
            temperature=settings.qwen_temperature,
        )
