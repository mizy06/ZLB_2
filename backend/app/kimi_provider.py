from __future__ import annotations

import json
import re
from typing import Any

import httpx

from .config import Settings
from .schemas import Chunk, ChunkExtraction


SYSTEM_PROMPT = """你是课程知识图谱抽取器。你的任务不是自由改写课程，而是提出可审计的候选节点与候选关系。

只输出一个 JSON 对象，格式：
{
  "nodes": [
    {
      "temp_id": "n1",
      "name": "简洁、唯一的知识点名称",
      "type": "concept|method|principle|process|formula|example|person|system",
      "definition": "仅依据原文的简短定义",
      "aliases": [],
      "confidence": 0.0
    }
  ],
  "edges": [
    {
      "source": "节点名称",
      "predicate": "is_a|part_of|depends_on|causes|used_for|includes|contrasts_with|related_to",
      "target": "节点名称",
      "confidence": 0.0
    }
  ]
}

规则：
1. 只抽取对理解课程有意义的知识点，不抽取“本章”“案例”等空泛词。
2. 所有节点和关系必须能由给定文本支持。
3. 关系的 source 和 target 必须对应 nodes 中的名称。
4. 不要输出 Markdown 代码块，不要解释。"""


class ModelProviderError(RuntimeError):
    pass


class OpenAICompatibleClient:
    def __init__(
        self,
        settings: Settings,
        api_key: str,
        base_url: str,
        provider_name: str,
    ):
        self.settings = settings
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.provider_name = provider_name

    async def list_models(self) -> list[str]:
        if not self.api_key:
            return []
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(
                    f"{self.base_url}/models",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
        except httpx.HTTPError as exc:
            raise ModelProviderError(f"Kimi 模型列表请求失败：{exc}") from exc

        if response.is_error:
            raise ModelProviderError(self._error_message(response))
        return [
            item["id"]
            for item in response.json().get("data", [])
            if item.get("id")
        ]

    async def check_model(self, model: str) -> tuple[bool, str]:
        if not self.api_key:
            return False, "未配置 KIMI_API_KEY"
        try:
            models = await self.list_models()
        except ModelProviderError as exc:
            return False, str(exc)
        if model in models:
            return True, "Kimi 模型与密钥可用"
        return False, f"Kimi 账号的模型列表中没有 {model}"

    async def extract(self, chunk: Chunk, model: str) -> ChunkExtraction:
        user_prompt = (
            f"章节：{chunk.heading or '未标注'}\n"
            f"位置：第 {chunk.index + 1} 个文本块\n\n"
            f"原文：\n{chunk.text}"
        )
        content = await self._chat(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=6000,
            json_mode=True,
        )
        return ChunkExtraction.model_validate(self._parse_json(content))

    async def complete_json(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 6000,
    ) -> dict[str, Any]:
        content = await self._chat(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
            json_mode=True,
        )
        return self._parse_json(content)

    async def complete_multimodal_json(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        image_data_url: str,
        max_tokens: int = 5000,
    ) -> dict[str, Any]:
        content = await self._chat(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": image_data_url},
                        },
                    ],
                },
            ],
            max_tokens=max_tokens,
            json_mode=True,
        )
        return self._parse_json(content)

    def _chat_payload(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        json_mode: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "reasoning_effort": self.settings.kimi_reasoning_effort,
            "max_completion_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        return payload

    async def _chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        json_mode: bool,
    ) -> str:
        if not self.api_key:
            raise ModelProviderError("未配置 KIMI_API_KEY")
        payload = self._chat_payload(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            json_mode=json_mode,
        )
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise ModelProviderError(f"Kimi 请求失败：{exc}") from exc

        if response.is_error:
            raise ModelProviderError(self._error_message(response))

        response_payload = response.json()
        try:
            content = response_payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelProviderError("Kimi 响应中没有可解析的输出") from exc
        if not isinstance(content, str) or not content.strip():
            raise ModelProviderError("Kimi 返回了空输出")
        return content

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            message = response.json().get("error", {}).get("message")
        except ValueError:
            message = response.text[:200]
        return message or f"Kimi 返回 HTTP {response.status_code}"

    @staticmethod
    def _parse_json(content: str) -> dict[str, Any]:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start >= 0 and end > start:
                try:
                    return json.loads(cleaned[start : end + 1])
                except json.JSONDecodeError as exc:
                    raise ModelProviderError("Kimi 没有返回有效 JSON") from exc
            raise ModelProviderError("Kimi 没有返回 JSON 对象")


class KimiClient(OpenAICompatibleClient):
    def __init__(self, settings: Settings):
        super().__init__(
            settings=settings,
            api_key=settings.kimi_api_key,
            base_url=settings.kimi_base_url,
            provider_name="kimi",
        )
