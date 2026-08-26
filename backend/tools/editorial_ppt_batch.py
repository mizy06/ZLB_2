from __future__ import annotations

import argparse
import asyncio
import hashlib
import html
import json
import os
import random
import re
import time
from pathlib import Path
from typing import Any, Sequence

from PIL import Image, ImageDraw, ImageFont, ImageOps

from backend.app.blackboard import SQLiteBlackboard
from backend.app.config import settings
from backend.app.editorial_ppt_pipeline import run_editorial_ppt_pipeline
from backend.app.export_service import render_mindmap_png


DEFAULT_SEED = 20260731
FONT_CANDIDATES = (
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Deterministically sample PPTX candidates, run the global-editor "
            "pipeline, and export JSON/PNG review artifacts."
        )
    )
    parser.add_argument(
        "--candidate-root",
        action="append",
        default=[],
        type=Path,
        help="Directory scanned recursively for PPT/PPTX candidates.",
    )
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        type=Path,
        help="Explicit PPT/PPTX candidate path; may be repeated.",
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--max-revisions",
        type=int,
        default=1,
        choices=(0, 1, 2, 3),
    )
    parser.add_argument(
        "--model",
        default="",
        help="Vision model override; defaults to configured Qwen vision model.",
    )
    return parser


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _candidate_paths(
    roots: Sequence[Path],
    explicit: Sequence[Path],
) -> list[tuple[Path, str]]:
    paths = [
        path.resolve()
        for path in explicit
        if path.is_file() and path.suffix.casefold() == ".pptx"
    ]
    for root in roots:
        resolved = root.resolve()
        if not resolved.is_dir():
            continue
        paths.extend(
            path.resolve()
            for path in resolved.rglob("*")
            if path.is_file()
            and path.suffix.casefold() == ".pptx"
        )

    unique: dict[str, Path] = {}
    for path in sorted(set(paths)):
        digest = _sha256(path)
        unique.setdefault(digest, path)
    return sorted(
        ((path, digest) for digest, path in unique.items()),
        key=lambda item: (item[0].name.casefold(), str(item[0])),
    )


def _select_candidates(
    candidates: Sequence[tuple[Path, str]],
    *,
    count: int,
    seed: int,
) -> list[tuple[Path, str]]:
    if count < 1:
        raise ValueError("count must be positive")
    if len(candidates) < count:
        raise ValueError(
            f"requested {count} candidates, but only {len(candidates)} "
            "unique PPT files were found"
        )
    if len(candidates) == count:
        return list(candidates)
    selected = random.Random(seed).sample(list(candidates), count)
    return sorted(selected, key=lambda item: str(item[0]))


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return slug[:48] or "ppt"


def _max_depth(result) -> int:
    return max((node.depth for node in result.nodes), default=0)


def _first_level_branches(result) -> list[str]:
    return [
        node.name
        for node in result.nodes
        if node.parent_id == result.root_id
    ]


def _font(size: int):
    for candidate in FONT_CANDIDATES:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def _contact_sheet(
    summaries: Sequence[dict[str, Any]],
    output_dir: Path,
) -> None:
    completed = [
        item
        for item in summaries
        if item.get("status") == "completed" and item.get("png_file")
    ]
    if not completed:
        return
    columns = 2
    cell_width = 900
    cell_height = 620
    rows = (len(completed) + columns - 1) // columns
    sheet = Image.new(
        "RGB",
        (columns * cell_width, rows * cell_height),
        "#f8fafc",
    )
    draw = ImageDraw.Draw(sheet)
    title_font = _font(24)
    for index, item in enumerate(completed):
        row, column = divmod(index, columns)
        left = column * cell_width
        top = row * cell_height
        image_path = output_dir / str(item["png_file"])
        with Image.open(image_path) as source:
            thumb = ImageOps.contain(
                source.convert("RGB"),
                (cell_width - 40, cell_height - 80),
                Image.Resampling.LANCZOS,
            )
        x = left + (cell_width - thumb.width) // 2
        y = top + 54 + (cell_height - 70 - thumb.height) // 2
        sheet.paste(thumb, (x, y))
        label = (
            f"{item['index']:02d}  {item['source_filename']}  "
            f"nodes={item['node_count']} depth={item['max_depth']}"
        )
        draw.text(
            (left + 20, top + 16),
            label,
            fill="#172033",
            font=title_font,
        )
    sheet.save(output_dir / "batch-contact-sheet.png", optimize=True)


def _html_report(
    summaries: Sequence[dict[str, Any]],
    output_dir: Path,
    *,
    candidate_count: int,
    seed: int,
) -> None:
    cards = []
    for item in summaries:
        title = html.escape(str(item["source_filename"]))
        if item["status"] == "completed":
            image = html.escape(str(item["png_file"]))
            branches = "".join(
                f"<li>{html.escape(branch)}</li>"
                for branch in item["first_level_branches"]
            )
            body = (
                f'<img src="{image}" alt="{title}">'
                f"<p>节点 {item['node_count']}，深度 {item['max_depth']}，"
                f"模型调用 {item['model_call_count']}，"
                f"修订 {item['revision_count']}，"
                f"最终阻断 {item['blocking_issue_count']}</p>"
                f"<ul>{branches}</ul>"
            )
        else:
            body = f"<pre>{html.escape(str(item.get('error', 'failed')))}</pre>"
        cards.append(f"<article><h2>{item['index']:02d}. {title}</h2>{body}</article>")
    page = f"""<!doctype html>
<html lang="zh-CN">
<meta charset="utf-8">
<title>Global-editor PPT batch</title>
<style>
body {{ margin: 0; padding: 24px; font-family: sans-serif; color: #172033; background: #f8fafc; }}
header {{ max-width: 1500px; margin: 0 auto 24px; }}
main {{ max-width: 1500px; margin: auto; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px; }}
article {{ background: white; border: 1px solid #dbe3ef; padding: 16px; border-radius: 6px; }}
h1, h2 {{ margin: 0 0 12px; letter-spacing: 0; }}
h2 {{ font-size: 18px; }}
img {{ display: block; width: 100%; height: 520px; object-fit: contain; background: #f8fafc; }}
p, li {{ line-height: 1.5; }}
@media (max-width: 900px) {{ main {{ grid-template-columns: 1fr; }} img {{ height: auto; }} }}
</style>
<header>
  <h1>Global-editor PPT batch</h1>
  <p>候选 {candidate_count}，固定随机种子 {seed}，选择 {len(summaries)}。</p>
</header>
<main>{''.join(cards)}</main>
</html>
"""
    (output_dir / "batch-report.html").write_text(page, encoding="utf-8")


async def _run(args: argparse.Namespace) -> int:
    candidates = _candidate_paths(args.candidate_root, args.source)
    selected = _select_candidates(
        candidates,
        count=args.count,
        seed=args.seed,
    )
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    selection = {
        "candidate_count": len(candidates),
        "selected_count": len(selected),
        "seed": args.seed,
        "selected": [
            {
                "source_path": str(path),
                "source_filename": path.name,
                "sha256": digest,
            }
            for path, digest in selected
        ],
    }
    (output_dir / "selection.json").write_text(
        json.dumps(selection, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if not settings.qwen_api_key:
        raise RuntimeError(
            "Qwen API key is not configured; mount the encrypted secret and "
            "age identity before running the batch"
        )
    blackboard = SQLiteBlackboard(settings.blackboard_path)
    summaries: list[dict[str, Any]] = []

    for index, (source, digest) in enumerate(selected, start=1):
        started = time.monotonic()
        slug = f"{index:02d}-{_safe_slug(source.stem)}-{digest[:8]}"
        task_id = f"editorial_{digest[:12]}_{index:02d}"
        events: list[dict[str, Any]] = []

        async def progress(stage: str, value: int, message: str) -> None:
            event = {
                "index": index,
                "stage": stage,
                "progress": value,
                "message": message,
            }
            events.append(event)
            print(json.dumps(event, ensure_ascii=False), flush=True)

        summary: dict[str, Any] = {
            "index": index,
            "slug": slug,
            "source_filename": source.name,
            "source_path": str(source),
            "source_sha256": digest,
            "status": "failed",
        }
        try:
            os.environ["MINDMAP_EDITORIAL_MAX_REVISIONS"] = str(
                args.max_revisions
            )
            if args.model:
                os.environ["MINDMAP_EDITORIAL_MODEL"] = args.model
            result = await run_editorial_ppt_pipeline(
                task_id=task_id,
                file_path=source,
                filename=source.name,
                model=args.model or settings.qwen_vision_model,
                provider="qwen",
                mode="standard",
                use_ai=True,
                progress=progress,
                blackboard=blackboard,
            )
            result_path = output_dir / f"{slug}.json"
            result_path.write_text(
                json.dumps(
                    result.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            png_path = output_dir / f"{slug}.png"
            png_path.write_bytes(render_mindmap_png(result))
            summary.update(
                {
                    "status": "completed",
                    "elapsed_seconds": round(time.monotonic() - started, 1),
                    "title": result.document.title,
                    "slide_count": int(
                        result.document.parse_metadata.get(
                            "ppt_slide_count",
                            0,
                        )
                    ),
                    "node_count": len(result.nodes),
                    "tree_edge_count": len(result.tree_edges),
                    "max_depth": _max_depth(result),
                    "first_level_count": len(
                        _first_level_branches(result)
                    ),
                    "first_level_branches": _first_level_branches(result),
                    "model_call_count": int(
                        result.document.parse_metadata.get(
                            "model_call_count",
                            0,
                        )
                    ),
                    "revision_count": int(
                        result.run_manifest.get(
                            "actual_editorial_revisions",
                            0,
                        )
                    ),
                    "final_issue_count": int(
                        result.run_manifest.get(
                            "final_review_issue_count",
                            0,
                        )
                    ),
                    "blocking_issue_count": int(
                        result.run_manifest.get(
                            "final_blocking_issue_count",
                            0,
                        )
                    ),
                    "quality_gate_passed": (
                        result.quality_report.quality_gate_passed
                    ),
                    "degraded_components": result.degraded_components,
                    "warnings": result.warnings,
                    "json_file": result_path.name,
                    "png_file": png_path.name,
                    "progress_events": events,
                }
            )
        except Exception as exc:
            summary.update(
                {
                    "elapsed_seconds": round(time.monotonic() - started, 1),
                    "error": str(exc),
                    "progress_events": events,
                }
            )
        summaries.append(summary)
        (output_dir / f"{slug}-summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (output_dir / "batch-summary.json").write_text(
            json.dumps(summaries, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    _contact_sheet(summaries, output_dir)
    _html_report(
        summaries,
        output_dir,
        candidate_count=len(candidates),
        seed=args.seed,
    )
    completed = sum(item["status"] == "completed" for item in summaries)
    return 0 if completed == len(summaries) else 1


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
