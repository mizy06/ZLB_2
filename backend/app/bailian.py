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
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{self.base_url}/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            response.raise_for_status()
            return [
                item["id"]
                for item in response.json().get("data", [])
                if item.get("id")
            ]

    async def check_model(self, model: str) -> tuple[bool, str]:
        if not self.api_key:
            return False, "未配置 API Key"
        try:
            await self._chat(
                model=model,
                messages=[{"role": "user", "content": "只回复 OK"}],
                max_tokens=8,
                json_mode=False,
            )
            return True, "模型可调用"
        except ModelProviderError as exc:
            return False, str(exc)

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

    async def _chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        json_mode: bool,
    ) -> str:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": max_tokens,
        }
        if self.provider_name == "deepseek":
            payload["reasoning_effort"] = "low"
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise ModelProviderError(
                f"{self.provider_name} 请求失败：{exc}"
            ) from exc

        if response.is_error:
            try:
                message = response.json().get("error", {}).get("message")
            except ValueError:
                message = response.text[:200]
            raise ModelProviderError(
                message or f"{self.provider_name} 返回 HTTP {response.status_code}"
            )

        payload = response.json()
        try:
            return payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelProviderError("模型响应中没有可解析的输出") from exc

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
                    raise ModelProviderError("模型没有返回有效 JSON") from exc
            raise ModelProviderError("模型没有返回 JSON 对象")


class BailianClient(OpenAICompatibleClient):
    def __init__(self, settings: Settings):
        super().__init__(
            settings=settings,
            api_key=settings.api_key,
            base_url=settings.openai_base_url,
            provider_name="bailian",
        )


class DeepSeekClient(OpenAICompatibleClient):
    def __init__(self, settings: Settings):
        super().__init__(
            settings=settings,
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            provider_name="deepseek",
        )
