from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import platform
import re
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Sequence

from PIL import Image
from pydantic import ValidationError

from backend.app.agents import RoleRuntime
from backend.app.config import settings
from backend.app.model_provider import ModelProviderError
from backend.app.pdf_layout_knowledge import (
    LayoutKnowledgePageResult,
    LayoutProfile,
    extract_page_layout_knowledge,
)
from backend.app.pdf_page_knowledge import (
    PAGE_KNOWLEDGE_MAX_COMPLETION_TOKENS,
    PAGE_KNOWLEDGE_MAX_OUTPUT_TOKENS,
    PAGE_KNOWLEDGE_SCHEMA_VERSION,
    PAGE_KNOWLEDGE_THINKING_BUDGET,
    PAGE_KNOWLEDGE_TIMEOUT_SECONDS,
    PDF_PAGE_KNOWLEDGE_PROMPT,
    PageKnowledgeExtraction,
    _data_url,
    _repair_guidance,
    _validation_issue_codes,
    page_knowledge_issues,
)
from backend.app.qwen_provider import QwenClient
from backend.app.runtime_manifest import runtime_versions, sanitize_endpoint
from backend.tools.pdf_quality_oracle import (
    audit_formulas as _formula_audit,
    audit_required_text as _text_coverage,
    canonicalize as _canonical,
)


Profile = Literal["direct", "dots", "chandra"]
DEFAULT_PAGES = (17, 42, 84, 85, 86, 87, 88, 92)
CANARY_PAGES = (
    17,
    18,
    21,
    29,
    32,
    34,
    35,
    42,
    47,
    62,
    84,
    85,
    86,
    87,
    88,
    92,
)

EXPECTED_FORMULAS: dict[int, tuple[str, ...]] = {
    17: (
        "U=-e^2/(4πε_0r)",
        "L̂_x=iℏ(sinφ∂/∂θ+ctgθcosφ∂/∂φ)",
        "L̂_y=iℏ(-cosφ∂/∂θ+ctgθsinφ∂/∂φ)",
        "L̂_z=-iℏ∂/∂φ",
        "L̂^2=L̂⃗·L̂⃗=L̂_x^2+L̂_y^2+L̂_z^2",
    ),
    18: (
        "L̂_zΦ=L_zΦ",
        "-iℏdΦ(φ)/dφ=L_zΦ(φ)",
        "L_z=const",
        "dΦ(φ)/Φ=(i/ℏ)L_zdφ",
        "Φ(φ)=Ae^((i/ℏ)L_zφ)",
    ),
    21: (
        "Y_00(θ,φ)=1/√(4π)",
        "Y_10(θ,φ)=√(3/(4π))cosθ",
        "Y_1±1(θ,φ)=∓√(3/(8π))sinθ·e^(±iφ)",
    ),
    29: (
        (
            "P_lm_l(θ,φ)dΩ="
            "{∫_0^∞|R_nl(r)|^2r^2dr}"
            "|Y_lm_l(θ,φ)|^2dΩ="
            "|Y_lm_l(θ,φ)|^2dΩ"
        ),
        "Y_00(θ,φ)=1/√(4π)",
        "|Y_00(θ,φ)|^2=1/(4π)",
    ),
    32: (
        "n=2,l=0,1",
        "r=r_2=4r_1=2^2r_1",
        "n=3,l=0,1,2",
        "r=r_3=3^2r_1",
        "r_n=n^2r_1",
    ),
    34: (
        "L⃗→μ⃗",
        (
            "μ⃗=-i·πr^2·n̂=(-v/(2πr))·e·πr^2·n̂="
            "(-e/(2m_e))·m_evr·n̂=(-e/(2m_e))L⃗"
        ),
        "μ_z=(-e/(2m_e))L_z=(-e/(2m_e))·m_lℏ",
    ),
    35: (
        "μ_B=eℏ/(2m_e)",
        "μ_B=9.27×10^-24 J/T",
        "μ_z=-(e/(2m_e))L_z=-μ_Bm_l",
        "∂B_x/∂z=∂B_y/∂z=0,∂B_z/∂z≠0",
        "E=-μ⃗·B⃗",
        (
            "F_z=-∂E/∂z=μ_z∂B_z/∂z="
            "-m_lμ_B∂B_z/∂z"
        ),
    ),
    42: (
        "2s+1=2→s=1/2",
        "m_s=+1/2,-1/2",
        "S=√(s(s+1))ℏ=√(1/2(1/2+1))ℏ=(√3/2)ℏ",
        "S_z=m_sℏ=±1/2ℏ",
        "μ⃗_s=-(e/m_e)S⃗",
        (
            "μ_{s,z}=-(e/m_e)m_sℏ="
            "∓(eℏ/(2m_e))=∓μ_B"
        ),
    ),
    47: (),
    62: (
        "(n+0.7l)大→E大",
        "E_3,2(3d态)>E_4,0(4s态)",
    ),
    84: (
        "Δν≈1.3×10^9 Hz",
        "ν=c/λ=3×10^8/(0.6328×10^-6)≈5×10^14 Hz",
    ),
    85: (
        "Δν/ν=1.3×10^9/(5×10^14)≈3×10^-6",
        "10^-15",
    ),
    86: (
        "nL=kλ_k/2",
        "λ_k=2nL/k",
    ),
    87: (
        "ν_k=c/λ_k=kc/(2nL)",
        "Δν_k=c/(2nL)",
        "L~1m",
        "n~1.0",
        "c~3×10^8 m/s",
        "Δν_k=c/(2nL)=3×10^8/(2×1×1)=1.5×10^8 Hz",
    ),
    88: (
        "Δν=1.3×10^9 Hz",
        "N=Δν/Δν_k=1.3×10^9/(1.5×10^8)≈8",
    ),
    92: (
        "B~10^16 W/m²·Sr~10^10 B_太阳",
        "B=Δp/(ΔS·ΔΩ)",
        "脉冲瞬时功率可达>10^14 W",
        "I>10^11 W/m²",
        "I>10^17 W/cm²",
        "10^8 K",
    ),
}

REQUIRED_TEXT: dict[int, tuple[str, ...]] = {
    17: ("氢原子中电子的电势能", "球极"),
    18: ("本征方程", "分离变量"),
    21: ("共同的本征函数", "球谐函数"),
    29: ("电子出现在", "各向同性"),
    32: ("概率最大", "l=n-1"),
    34: ("角动量和磁矩的关系", "验证角动量空间量子化"),
    35: ("玻耳磁子", "磁矩在 z向受力"),
    42: ("电子自旋是一种", "不是小球自转"),
    47: ("分析非常靠近原子核", "l 小的靠近核的概率大"),
    62: ("能量最小原理", "电子优先占据最低能态"),
    84: ("谱线是有一定的宽度", "称为一个纵模"),
    85: ("它们要产生干涉", "在超高稳频条件下"),
    86: ("反射镜处必是波节", "只有产生相长干涉才有输出"),
    87: ("可以存在的频率", "相邻两种频率的间隔"),
    88: ("可以存在的纵模个数", "使输出纵模个数减少"),
    92: ("非聚焦状态", "引起核聚变"),
}

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(
        min(round((len(ordered) - 1) * percentile), len(ordered) - 1),
        0,
    )
    return round(ordered[index], 3)


def _benchmark_page_status(
    *,
    available: bool,
    issues: Sequence[str],
) -> str:
    if not available:
        return "failed"
    if issues:
        return "degraded"
    return "accepted"


def _extraction_metrics(
    extraction: PageKnowledgeExtraction | None,
    layout_result: LayoutKnowledgePageResult | None,
    *,
    page: int,
) -> dict[str, Any]:
    nodes = list(extraction.nodes) if extraction is not None else []
    node_evidence = [node.evidence_text for node in nodes]
    final_formulas = [
        node.formula_text for node in nodes if node.formula_text
    ]
    layout_formulas: list[str] = []
    layout_evidence: list[str] = []
    inherited = 0
    if layout_result is not None and layout_result.layout is not None:
        blocks = layout_result.layout.blocks
        layout_evidence = [block.text for block in blocks]
        layout_formulas = [
            formula.text
            for block in blocks
            for formula in block.formulas
        ]
        for node in nodes:
            if any(
                node.evidence_text == block.text
                and node.bbox == block.bbox
                and (
                    not node.formula_text
                    or any(
                        _canonical(node.formula_text)
                        == _canonical(formula.text)
                        and _canonical(node.formula_latex)
                        == _canonical(formula.latex)
                        for formula in block.formulas
                    )
                )
                for block in blocks
            ):
                inherited += 1
    duplicate_keys = [
        (_canonical(node.name), _canonical(node.evidence_text))
        for node in nodes
    ]
    duplicate_count = len(duplicate_keys) - len(set(duplicate_keys))
    node_formula_audit = _formula_audit(
        final_formulas,
        EXPECTED_FORMULAS.get(page, ()),
    )
    layout_formula_audit = _formula_audit(
        layout_formulas,
        EXPECTED_FORMULAS.get(page, ()),
    )
    node_required_coverage = _text_coverage(
        node_evidence,
        REQUIRED_TEXT.get(page, ()),
    )
    layout_required_coverage = _text_coverage(
        layout_evidence,
        REQUIRED_TEXT.get(page, ()),
    )
    return {
        "node_count": len(nodes),
        "formula_count": len(final_formulas),
        "layout_formula_count": len(layout_formulas),
        "bbox_legal_rate": 1.0 if nodes else 0.0,
        "evidence_inheritance_rate": (
            round(inherited / len(nodes), 4)
            if layout_result is not None and nodes
            else None
        ),
        "duplicate_count": duplicate_count,
        "duplicate_rate": (
            round(duplicate_count / len(nodes), 4) if nodes else 0.0
        ),
        "formula_audit": node_formula_audit,
        "layout_formula_audit": layout_formula_audit,
        "required_coverage": node_required_coverage,
        "layout_required_coverage": layout_required_coverage,
    }


async def _direct_page(
    *,
    image_path: Path,
    page: int,
    runtime: RoleRuntime,
    min_confidence: float,
    max_attempts: int,
) -> tuple[PageKnowledgeExtraction | None, int, list[str]]:
    if runtime.client is None:
        return None, 0, ["model_unavailable"]
    with Image.open(image_path) as image:
        width, height = image.size
    image_data_url = await asyncio.to_thread(_data_url, image_path)
    last_issues: list[str] = []
    attempts = max(int(max_attempts), 1)
    for attempt in range(1, attempts + 1):
        repair = ""
        if last_issues:
            repair = (
                "上一次输出未通过质量门："
                + "、".join(last_issues[:8])
                + "。"
                + _repair_guidance(last_issues)
                + "请逐项修正。"
            )
        try:
            payload = await runtime.client.complete_multimodal_json(
                model=runtime.model,
                system_prompt=PDF_PAGE_KNOWLEDGE_PROMPT,
                user_prompt=(
                    f"提取第 {page} 页的知识节点。"
                    f"页面像素尺寸：{width}×{height}。"
                    f"这是本页第 {attempt} 次独立尝试。{repair}"
                ),
                image_data_url=image_data_url,
                max_tokens=PAGE_KNOWLEDGE_MAX_OUTPUT_TOKENS,
                max_completion_tokens=(
                    PAGE_KNOWLEDGE_MAX_COMPLETION_TOKENS
                ),
                thinking_budget=PAGE_KNOWLEDGE_THINKING_BUDGET,
                max_attempts=1,
                timeout_seconds=PAGE_KNOWLEDGE_TIMEOUT_SECONDS,
            )
            extraction = PageKnowledgeExtraction.model_validate(payload)
            issues = page_knowledge_issues(
                extraction,
                expected_page=page,
                min_confidence=min_confidence,
                page_has_text_signal=True,
            )
            if not issues:
                return extraction, attempt, []
            last_issues = list(issues)
        except ValidationError as exc:
            last_issues = _validation_issue_codes(exc)
        except (ModelProviderError, ValueError) as exc:
            last_issues = [type(exc).__name__]
    return None, attempts, last_issues


async def _run_profile(
    *,
    profile: Profile,
    concurrency: int,
    pages: Sequence[int],
    image_dir: Path,
    min_confidence: float,
    max_attempts: int,
    layout_only: bool,
) -> dict[str, Any]:
    if layout_only and profile == "direct":
        raise ValueError("layout-only benchmark cannot use direct profile")
    records: list[dict[str, Any]] = []
    client = QwenClient(settings)
    client.attempt_recorder = records.append
    runtime = RoleRuntime(
        provider="qwen",
        model=settings.qwen_vision_model,
        client=client,
        available=settings.key_configured,
        unavailable_reason=settings.qwen_secret_error,
    )
    semaphore = asyncio.Semaphore(max(int(concurrency), 1))

    async def run_page(page: int) -> dict[str, Any]:
        image_path = image_dir / f"page_{page:04d}.png"
        started = time.perf_counter()
        async with semaphore:
            if profile == "direct":
                extraction, attempts, issues = await _direct_page(
                    image_path=image_path,
                    page=page,
                    runtime=runtime,
                    min_confidence=min_confidence,
                    max_attempts=max_attempts,
                )
                layout_result = None
                layout_attempts = 0
                node_attempts = attempts
            else:
                layout_result = await extract_page_layout_knowledge(
                    image_path=image_path,
                    page=page,
                    runtime=runtime,
                    profile=profile,
                    min_confidence=min_confidence,
                    max_layout_attempts=max_attempts,
                    max_node_attempts=max_attempts,
                    extract_nodes=not layout_only,
                )
                extraction = layout_result.extraction
                issues = list(layout_result.issues)
                layout_attempts = layout_result.layout_attempts
                node_attempts = layout_result.node_attempts
        elapsed = round(time.perf_counter() - started, 3)
        available = (
            layout_result is not None
            and layout_result.layout is not None
            if layout_only
            else extraction is not None
        )
        status = _benchmark_page_status(
            available=available,
            issues=issues,
        )
        return {
            "page": page,
            "status": status,
            "elapsed_seconds": elapsed,
            "layout_attempts": layout_attempts,
            "node_attempts": node_attempts,
            "issues": issues,
            "metrics": _extraction_metrics(
                extraction,
                layout_result,
                page=page,
            ),
            "layout": (
                layout_result.layout.model_dump(mode="json")
                if layout_result is not None
                and layout_result.layout is not None
                else None
            ),
            "extraction": (
                extraction.model_dump(mode="json")
                if extraction is not None
                else None
            ),
        }

    started = time.perf_counter()
    page_results = await asyncio.gather(*(run_page(page) for page in pages))
    elapsed = round(time.perf_counter() - started, 3)
    latencies = [
        float(record.get("latency_ms", 0))
        for record in records
        if record.get("operation") == "chat_completion"
    ]
    accepted = [
        item["page"]
        for item in page_results
        if item["status"] == "accepted"
    ]
    degraded = [
        item["page"]
        for item in page_results
        if item["status"] == "degraded"
    ]
    failed = [
        item["page"]
        for item in page_results
        if item["status"] == "failed"
    ]
    formula_rows = [
        item["metrics"]["formula_audit"]
        for item in page_results
    ]
    expected_formula_count = sum(
        row["expected_count"] for row in formula_rows
    )
    exact_formula_count = sum(row["exact_count"] for row in formula_rows)
    layout_formula_rows = [
        item["metrics"]["layout_formula_audit"]
        for item in page_results
    ]
    layout_expected_formula_count = sum(
        row["expected_count"] for row in layout_formula_rows
    )
    layout_exact_formula_count = sum(
        row["exact_count"] for row in layout_formula_rows
    )
    required_rows = [
        item["metrics"]["required_coverage"]
        for item in page_results
    ]
    required_count = sum(row["required_count"] for row in required_rows)
    covered_count = sum(row["covered_count"] for row in required_rows)
    layout_required_rows = [
        item["metrics"]["layout_required_coverage"]
        for item in page_results
    ]
    layout_required_count = sum(
        row["required_count"] for row in layout_required_rows
    )
    layout_covered_count = sum(
        row["covered_count"] for row in layout_required_rows
    )
    return {
        "profile": profile,
        "concurrency": concurrency,
        "elapsed_seconds": elapsed,
        "summary": {
            "accepted_pages": accepted,
            "degraded_pages": degraded,
            "failed_pages": failed,
            "page_success_rate": round(len(accepted) / len(pages), 4),
            "page_completion_rate": round(
                (len(accepted) + len(degraded)) / len(pages),
                4,
            ),
            "http_attempts": len(latencies),
            "http_latency_p50_ms": _percentile(latencies, 0.5),
            "http_latency_p95_ms": _percentile(latencies, 0.95),
            "http_latency_max_ms": round(max(latencies), 3)
            if latencies
            else 0.0,
            "page_latency_p50_seconds": _percentile(
                [item["elapsed_seconds"] for item in page_results],
                0.5,
            ),
            "page_latency_p95_seconds": _percentile(
                [item["elapsed_seconds"] for item in page_results],
                0.95,
            ),
            "canonical_formula_exact_rate": round(
                exact_formula_count / expected_formula_count,
                4,
            )
            if expected_formula_count
            else 1.0,
            "layout_canonical_formula_exact_rate": round(
                layout_exact_formula_count
                / layout_expected_formula_count,
                4,
            )
            if layout_expected_formula_count
            else None,
            "required_coverage_rate": round(
                covered_count / required_count,
                4,
            )
            if required_count
            else 1.0,
            "layout_required_coverage_rate": round(
                layout_covered_count / layout_required_count,
                4,
            )
            if layout_required_count
            else None,
            "node_count": sum(
                item["metrics"]["node_count"] for item in page_results
            ),
            "duplicate_count": sum(
                item["metrics"]["duplicate_count"]
                for item in page_results
            ),
        },
        "pages": page_results,
        "safe_attempt_records": records,
    }


def _versions() -> dict[str, str]:
    packages = (
        "Pillow",
        "pydantic",
        "httpx",
        "pdfplumber",
        "pylatexenc",
        "pypdf",
    )
    versions: dict[str, str] = {}
    for package in packages:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "not-installed"
    return versions


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    if not settings.key_configured:
        raise RuntimeError(
            f"Qwen credential unavailable: {settings.qwen_secret_error}"
        )
    pages = tuple(args.pages)
    profiles = tuple(args.profiles)
    concurrencies = tuple(args.concurrencies)
    image_hashes = {
        str(page): _sha256(
            args.image_dir / f"page_{page:04d}.png"
        )
        for page in pages
    }
    runs: list[dict[str, Any]] = []
    for concurrency in concurrencies:
        for profile in profiles:
            runs.append(
                await _run_profile(
                    profile=profile,
                    concurrency=concurrency,
                    pages=pages,
                    image_dir=args.image_dir,
                    min_confidence=args.min_confidence,
                    max_attempts=args.max_attempts,
                    layout_only=args.layout_only,
                )
            )
    return {
        "manifest": {
            "created_at": datetime.now(UTC).isoformat(),
            "python": platform.python_version(),
            "packages": _versions(),
            "provider": "qwen",
            "model": settings.qwen_vision_model,
            "base_url": sanitize_endpoint(settings.qwen_base_url),
            "provider_endpoint": sanitize_endpoint(settings.qwen_base_url),
            "credential_source": settings.qwen_secret_source,
            "runtime_versions": dict(runtime_versions()),
            "direct_schema_version": PAGE_KNOWLEDGE_SCHEMA_VERSION,
            "pages": list(pages),
            "profiles": list(profiles),
            "concurrencies": list(concurrencies),
            "min_confidence": args.min_confidence,
            "max_attempts": args.max_attempts,
            "stage": "layout_only" if args.layout_only else "layout_nodes",
            "image_dir": str(args.image_dir),
            "image_sha256": image_hashes,
        },
        "runs": runs,
    }


def _csv_profiles(value: str) -> list[Profile]:
    parsed = [item.strip() for item in value.split(",") if item.strip()]
    allowed = {"direct", "dots", "chandra"}
    if not parsed or any(item not in allowed for item in parsed):
        raise argparse.ArgumentTypeError(
            "profiles must be direct,dots,chandra"
        )
    return parsed  # type: ignore[return-value]


def _csv_ints(value: str) -> list[int]:
    try:
        parsed = [int(item.strip()) for item in value.split(",")]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "expected comma-separated integers"
        ) from exc
    if not parsed or any(item < 1 for item in parsed):
        raise argparse.ArgumentTypeError("values must be positive")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run isolated Qwen direct/dots/Chandra PDF-page A/B.",
    )
    parser.add_argument("--image-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--profiles",
        type=_csv_profiles,
        default=["direct", "dots", "chandra"],
    )
    parser.add_argument(
        "--concurrencies",
        type=_csv_ints,
        default=[1, 4, 8],
    )
    parser.add_argument(
        "--pages",
        type=_csv_ints,
        default=list(DEFAULT_PAGES),
    )
    parser.add_argument("--min-confidence", type=float, default=0.85)
    parser.add_argument("--max-attempts", type=int, default=1)
    parser.add_argument(
        "--layout-only",
        action="store_true",
        help="Benchmark only dots/Chandra page-layout extraction.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    args.image_dir = args.image_dir.resolve()
    args.output = args.output.resolve()
    result = asyncio.run(_run(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summaries = [
        {
            "profile": run["profile"],
            "concurrency": run["concurrency"],
            **run["summary"],
            "elapsed_seconds": run["elapsed_seconds"],
        }
        for run in result["runs"]
    ]
    print(json.dumps(summaries, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
