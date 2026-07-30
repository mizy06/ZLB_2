from __future__ import annotations

import unittest

from backend.app.agents import _evidence_matches_unit
from backend.app.architecture_schemas import ContentUnit
from backend.app.mindmap_engine.schemas import EvidenceRef


def _unit(
    text: str,
    *,
    unit_id: str = "unit-1",
    evidence_excerpt: str = "",
) -> ContentUnit:
    return ContentUnit(
        id=unit_id,
        document_id="doc",
        kind="text",
        text=text,
        evidence_excerpt=evidence_excerpt,
        importance=0.8,
    )


def _evidence(
    excerpt: str,
    *,
    unit_id: str = "unit-1",
    chunk_id: str | None = None,
) -> EvidenceRef:
    return EvidenceRef(
        unit_id=unit_id,
        chunk_id=chunk_id,
        excerpt=excerpt,
    )


class EvidenceCanonicalAlignmentTDDTests(unittest.TestCase):
    def test_near_verbatim_unicode_and_ocr_variants_align(self):
        cases = [
            (
                "电子的自旋—轨道耦合，会使能级发生精细分裂。",
                "电子的自旋-轨道耦合,会使能级发生精细分裂.",
            ),
            (
                "波函数 ψ（ｘ）满足归一化条件。",
                "波函数 ψ(x)满足归一化条件。",
            ),
            (
                "能级公式为 Eₙ＝−13.6 eV／n²。",
                "能级公式为 En=-13.6 eV/n2。",
            ),
            (
                "晶格常数约为 2 × 10⁻¹⁰ m。",
                "晶格常数约为2*10-10m。",
            ),
            (
                "The wave-packet inter-\naction determines "
                "the transition probability.",
                "The wave-packet interaction determines "
                "the transition probability.",
            ),
            (
                "The photo\u00adelectric effect demonstrates "
                "quantized energy transfer.",
                "The photoelectric effect demonstrates "
                "quantized energy transfer.",
            ),
        ]

        for source, excerpt in cases:
            with self.subTest(excerpt=excerpt):
                self.assertTrue(
                    _evidence_matches_unit(
                        _evidence(excerpt),
                        _unit(source),
                    )
                )

    def test_declared_unit_and_chunk_binding_must_match(self):
        unit = _unit("梯度下降通过迭代更新参数来降低损失函数。")
        exact_excerpt = "梯度下降通过迭代更新参数来降低损失函数。"

        self.assertFalse(
            _evidence_matches_unit(
                _evidence(exact_excerpt, unit_id="other-unit"),
                unit,
            )
        )
        self.assertFalse(
            _evidence_matches_unit(
                _evidence(
                    exact_excerpt,
                    unit_id=None,
                    chunk_id="other-chunk",
                ),
                unit,
            )
        )
        self.assertTrue(
            _evidence_matches_unit(
                _evidence(
                    exact_excerpt,
                    unit_id="unit-1",
                    chunk_id="legacy-source-chunk",
                ),
                unit,
            )
        )

    def test_short_generic_unrelated_and_semantic_rewrites_are_rejected(self):
        unit = _unit(
            "本节主要内容是：原子从较高能态降到较低能态，"
            "并释放一个光量子。"
        )
        rejected = [
            "主要内容",
            "原子",
            "电子由高能级跃迁至低能级时会发射光子。",
            "牛顿法通过海森矩阵求解。",
        ]

        for excerpt in rejected:
            with self.subTest(excerpt=excerpt):
                self.assertFalse(
                    _evidence_matches_unit(
                        _evidence(excerpt),
                        unit,
                    )
                )

    def test_alignment_does_not_bridge_separate_source_fields(self):
        unit = _unit(
            "波函数必须满足",
            evidence_excerpt="归一化条件与边界条件。",
        )

        self.assertFalse(
            _evidence_matches_unit(
                _evidence("满足归一化条件"),
                unit,
            )
        )

    def test_punctuation_normalization_does_not_erase_decimal_points(self):
        unit = _unit("圆周率近似为 3.14，而不是整数 314。")

        self.assertFalse(
            _evidence_matches_unit(
                _evidence("圆周率近似为314"),
                unit,
            )
        )


if __name__ == "__main__":
    unittest.main()
