from __future__ import annotations

import hashlib
import re

from .mindmap_engine.normalize import is_publishable_label
from .schemas import Chunk, ChunkExtraction, EdgeCandidate, Evidence, NodeCandidate


DEFINITION_PATTERNS = [
    re.compile(
        r"(?P<name>[\u4e00-\u9fffA-Za-z0-9·（）()_-]{2,24})"
        r"(?:是指|指的是|是|定义为|称为)"
        r"(?P<definition>[^。！？\n]{4,100})"
    ),
    re.compile(
        r"(?P<name>[\u4e00-\u9fffA-Za-z0-9·（）()_-]{2,24})"
        r"(?:包括|包含|由)"
        r"(?P<definition>[^。！？\n]{4,100})"
    ),
]

RELATION_PATTERNS = [
    ("includes", re.compile(r"(?P<a>[^，。；\n]{2,20})(?:包括|包含)(?P<b>[^，。；\n]{2,20})")),
    ("part_of", re.compile(r"(?P<a>[^，。；\n]{2,20})是(?P<b>[^，。；\n]{2,20})的(?:组成部分|一部分)")),
    ("depends_on", re.compile(r"(?P<a>[^，。；\n]{2,20})(?:依赖|取决于)(?P<b>[^，。；\n]{2,20})")),
    ("causes", re.compile(r"(?P<a>[^，。；\n]{2,20})(?:导致|引起)(?P<b>[^，。；\n]{2,20})")),
    ("used_for", re.compile(r"(?P<a>[^，。；\n]{2,20})(?:用于|可用来)(?P<b>[^，。；\n]{2,20})")),
]

def _clean_name(value: str) -> str:
    value = re.sub(
        r"^(?:\s*#+\s*|\s*[-•●▪◦‣⁃]\s*|"
        r"\s*(?:\d+|[一二三四五六七八九十]+)[、.)）]\s*)",
        "",
        value,
    )
    return re.sub(r"[ \t]+", " ", value).strip()


def _is_valid_label(value: str) -> bool:
    return len(value) <= 36 and is_publishable_label(value)


def _evidence(chunk: Chunk, excerpt: str) -> Evidence:
    return Evidence(
        chunk_id=chunk.id,
        excerpt=excerpt.strip()[:180],
        page=chunk.page_start,
        slide=chunk.slide_start,
    )


def heuristic_extract(chunk: Chunk) -> ChunkExtraction:
    nodes: dict[str, NodeCandidate] = {}
    edges: list[EdgeCandidate] = []

    def add_node(name: str, definition: str, confidence: float, excerpt: str) -> None:
        clean = _clean_name(name)
        if not _is_valid_label(clean):
            return
        key = clean.casefold()
        candidate = NodeCandidate(
            temp_id=f"tmp_{hashlib.sha1((chunk.id + clean).encode()).hexdigest()[:8]}",
            name=clean,
            type="concept",
            definition=definition.strip()[:160],
            confidence=confidence,
            evidence=[_evidence(chunk, excerpt)],
        )
        previous = nodes.get(key)
        if not previous or candidate.confidence > previous.confidence:
            nodes[key] = candidate

    if chunk.heading:
        add_node(chunk.heading, "文档中的章节主题", 0.62, chunk.heading)

    for line in chunk.text.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if 2 <= len(stripped) <= 32 and not re.search(r"[。！？]", stripped):
            add_node(stripped, "文档中出现的主题或术语", 0.48, stripped)

    for pattern in DEFINITION_PATTERNS:
        for match in pattern.finditer(chunk.text):
            excerpt = match.group(0)
            add_node(match.group("name"), match.group("definition"), 0.72, excerpt)

    for predicate, pattern in RELATION_PATTERNS:
        for match in pattern.finditer(chunk.text):
            source = _clean_name(match.group("a"))
            target = _clean_name(match.group("b"))
            if not _is_valid_label(source) or not _is_valid_label(target):
                continue
            add_node(source, "", 0.55, match.group(0))
            add_node(target, "", 0.55, match.group(0))
            edges.append(
                EdgeCandidate(
                    source=source,
                    predicate=predicate,
                    target=target,
                    confidence=0.58,
                    evidence=[_evidence(chunk, match.group(0))],
                )
            )

    ordered = sorted(nodes.values(), key=lambda item: item.confidence, reverse=True)[:14]
    allowed = {item.name for item in ordered}
    edges = [
        edge
        for edge in edges
        if edge.source in allowed and edge.target in allowed
    ][:18]

    if chunk.heading and len(ordered) > 1:
        for item in ordered:
            if item.name != chunk.heading and not any(
                edge.source == chunk.heading and edge.target == item.name
                for edge in edges
            ):
                edges.append(
                    EdgeCandidate(
                        source=chunk.heading,
                        predicate="includes",
                        target=item.name,
                        confidence=0.42,
                        evidence=item.evidence,
                    )
                )

    return ChunkExtraction(nodes=ordered, edges=edges)
