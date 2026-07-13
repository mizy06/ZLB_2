from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Awaitable, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from .bailian import (
    BailianClient,
    DeepSeekClient,
    ModelProviderError,
    OpenAICompatibleClient,
)
from .chunking import chunk_document
from .config import settings
from .document_parser import parse_document
from .graph_builder import build_graph
from .heuristics import heuristic_extract
from .schemas import (
    AnalysisResult,
    Chunk,
    ChunkExtraction,
    Evidence,
    KnowledgeEdge,
    KnowledgeNode,
    ParsedDocument,
    QualityReport,
)


ProgressCallback = Callable[[str, int, str], Awaitable[None]]


class PipelineState(TypedDict, total=False):
    task_id: str
    file_path: str
    filename: str
    model: str
    provider: str
    use_ai: bool
    document: ParsedDocument
    chunks: list[Chunk]
    extractions: list[ChunkExtraction]
    nodes: list[KnowledgeNode]
    edges: list[KnowledgeEdge]
    quality: QualityReport
    extraction_mode: str
    warnings: list[str]


def provider_client(provider: str) -> OpenAICompatibleClient:
    if provider == "deepseek":
        return DeepSeekClient(settings)
    return BailianClient(settings)


def create_pipeline(progress: ProgressCallback):
    async def parse_node(state: PipelineState):
        await progress("parse", 12, "正在解析文档结构")
        document = await asyncio.to_thread(
            parse_document,
            Path(state["file_path"]),
            state["filename"],
        )
        return {"document": document}

    async def chunk_node(state: PipelineState):
        await progress("chunk", 28, "正在按章节与位置生成 chunk")
        chunks = chunk_document(
            state["document"],
            max_chars=settings.max_chunk_chars,
            overlap_chars=settings.chunk_overlap_chars,
        )
        return {"chunks": chunks}

    async def extract_node(state: PipelineState):
        chunks = state["chunks"]
        provider = state.get("provider", "bailian")
        model = state.get("model") or (
            settings.deepseek_model if provider == "deepseek" else settings.model
        )
        client = provider_client(provider)
        warnings = list(state.get("warnings", []))
        use_ai = state.get("use_ai", True)
        ai_available = False
        if use_ai and client.api_key:
            await progress(
                "model_check",
                36,
                f"正在检查 {provider}/{model} 的调用权限",
            )
            ai_available, reason = await client.check_model(model)
            if not ai_available:
                warnings.append(
                    f"{provider} 模型不可用，已降级为本地抽取：{reason}"
                )
        elif use_ai:
            warnings.append(f"未配置 {provider} API Key，已降级为本地抽取。")

        semaphore = asyncio.Semaphore(settings.extraction_concurrency)
        completed = 0
        completed_lock = asyncio.Lock()

        async def extract_one(chunk: Chunk) -> tuple[ChunkExtraction, bool]:
            nonlocal completed
            used_ai = False
            async with semaphore:
                if ai_available:
                    try:
                        extraction = await client.extract(chunk, model)
                        used_ai = True
                    except ModelProviderError as exc:
                        warnings.append(
                            f"Chunk {chunk.index + 1} 模型抽取失败，已局部降级：{exc}"
                        )
                        extraction = heuristic_extract(chunk)
                else:
                    extraction = heuristic_extract(chunk)

            for node in extraction.nodes:
                if not node.evidence:
                    node.evidence = [
                        Evidence(
                            chunk_id=chunk.id,
                            excerpt=chunk.text[:180],
                            page=chunk.page_start,
                            slide=chunk.slide_start,
                        )
                    ]
            for edge in extraction.edges:
                if not edge.evidence:
                    edge.evidence = [
                        Evidence(
                            chunk_id=chunk.id,
                            excerpt=chunk.text[:180],
                            page=chunk.page_start,
                            slide=chunk.slide_start,
                        )
                    ]

            async with completed_lock:
                completed += 1
                ratio = completed / max(len(chunks), 1)
                await progress(
                    "extract",
                    38 + int(ratio * 34),
                    f"已完成 {completed}/{len(chunks)} 个 chunk",
                )
            return extraction, used_ai

        outputs = await asyncio.gather(*(extract_one(chunk) for chunk in chunks))
        extractions = [item[0] for item in outputs]
        ai_count = sum(1 for item in outputs if item[1])
        mode = (
            provider
            if ai_count == len(outputs) and outputs
            else "mixed"
            if ai_count and ai_count != len(outputs)
            else "heuristic"
        )
        return {
            "extractions": extractions,
            "extraction_mode": mode,
            "warnings": warnings,
        }

    async def graph_node(state: PipelineState):
        await progress("normalize", 80, "正在归一节点并校验关系")
        nodes, edges, quality = build_graph(state["extractions"])
        return {"nodes": nodes, "edges": edges, "quality": quality}

    async def finish_node(state: PipelineState):
        await progress("complete", 100, "知识图谱已生成")
        return {}

    builder = StateGraph(PipelineState)
    builder.add_node("parse", parse_node)
    builder.add_node("chunk", chunk_node)
    builder.add_node("extract", extract_node)
    builder.add_node("normalize", graph_node)
    builder.add_node("finish", finish_node)
    builder.add_edge(START, "parse")
    builder.add_edge("parse", "chunk")
    builder.add_edge("chunk", "extract")
    builder.add_edge("extract", "normalize")
    builder.add_edge("normalize", "finish")
    builder.add_edge("finish", END)
    return builder.compile()


async def run_pipeline(
    task_id: str,
    file_path: Path,
    filename: str,
    model: str,
    provider: str,
    use_ai: bool,
    progress: ProgressCallback,
) -> AnalysisResult:
    graph = create_pipeline(progress)
    state = await graph.ainvoke(
        {
            "task_id": task_id,
            "file_path": str(file_path),
            "filename": filename,
            "model": model,
            "provider": provider,
            "use_ai": use_ai,
            "warnings": [],
        }
    )
    return AnalysisResult(
        task_id=task_id,
        document=state["document"],
        chunks=state["chunks"],
        nodes=state["nodes"],
        edges=state["edges"],
        quality=state["quality"],
        extraction_mode=state["extraction_mode"],
        provider=(
            provider
            if state["extraction_mode"] != "heuristic"
            else "heuristic"
        ),
        model=model if state["extraction_mode"] != "heuristic" else None,
        warnings=state.get("warnings", []),
    )
