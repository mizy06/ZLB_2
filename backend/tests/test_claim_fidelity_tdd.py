from __future__ import annotations

import unittest

from backend.app.claim_fidelity import (
    claim_fidelity_issues,
    claim_is_faithful,
    hard_claim_fidelity_issues,
)


class ClaimFidelityTDDTests(unittest.TestCase):
    def test_rejects_formal_export_formula_missing_from_evidence(self):
        definition = (
            "谐振腔两端反射镜处必为波节，光程满足 "
            "nkλ/2 = L（k=1,2,3,…）时才能产生相长干涉从而有输出"
        )
        evidence = [
            "因为谐振腔两端反射镜处必是波节， "
            "所以有光程 ( k=1、2、3、…．)"
        ]

        issues = claim_fidelity_issues(definition, evidence)

        self.assertFalse(claim_is_faithful(definition, evidence))
        self.assertIn(
            "unsupported_relation",
            {issue.code for issue in issues},
        )
        self.assertTrue(
            any("nkλ/2=l" in issue.fragment for issue in issues)
        )

    def test_rejects_formal_export_dimensionful_extreme_without_unit(self):
        definition = (
            "He-Ne激光器在超高稳频条件下输出线宽可小到10⁻¹⁵量级，"
            "因为谐振腔的选模作用使得只有满足驻波条件的极少数频率能振荡"
        )
        evidence = [
            "而He—Ne激光器输出激光的在超高稳频条件下，"
            "却会小到10 - 15 为什么？"
        ]

        issues = claim_fidelity_issues(definition, evidence)

        self.assertFalse(claim_is_faithful(definition, evidence))
        self.assertIn(
            "extreme_scientific_value_missing_dimension",
            {issue.code for issue in issues},
        )

    def test_protects_supported_relations_numbers_units_and_ratios(self):
        accepted = [
            ("能级满足 E_n=E_1/n²。", ["原文给出 Eₙ = E₁ / n²。"]),
            ("角动量满足 L_z=m_l ħ。", ["可写成 L_z = m_l ℏ。"]),
            ("激光波长为632.8nm。", ["He-Ne激光波长为 632.8 nm。"]),
            (
                "该事件发生概率约为10^-15。",
                ["实验给出的概率约为 10⁻¹⁵。"],
            ),
            (
                "相对线宽满足 Δν/ν≈10^-15。",
                ["超高稳频时 Δν / ν ≈ 10⁻¹⁵。"],
            ),
            (
                "输出线宽约为10^-15Hz。",
                ["测得输出线宽约为 10⁻¹⁵ Hz。"],
            ),
        ]

        for definition, evidence in accepted:
            with self.subTest(definition=definition):
                self.assertEqual(
                    claim_fidelity_issues(definition, evidence),
                    (),
                )
                self.assertTrue(
                    claim_is_faithful(definition, evidence)
                )

    def test_rejects_changed_key_number_without_fuzzy_matching(self):
        definition = "He-Ne激光的波长为632.8nm。"
        evidence = ["He-Ne激光的波长约为633 nm。"]

        issues = claim_fidelity_issues(definition, evidence)

        self.assertIn(
            "unsupported_number",
            {issue.code for issue in issues},
        )
        self.assertFalse(claim_is_faithful(definition, evidence))

    def test_relation_and_number_cannot_bridge_separate_evidence_items(self):
        definition = "能级满足 E_n=E_1/n²。"
        evidence = ["能级符号记为 E_n =", "另一处出现 E_1/n²。"]

        issues = claim_fidelity_issues(definition, evidence)

        self.assertIn(
            "unsupported_relation",
            {issue.code for issue in issues},
        )

    def test_rejects_semantic_number_rewrite_without_exact_digits(self):
        definition = "He-Ne激光的波长为632.8nm。"
        evidence = ["He-Ne激光的波长约为六百三十二点八纳米。"]

        self.assertFalse(claim_is_faithful(definition, evidence))

    def test_separates_missing_relation_from_conflicting_relation(self):
        missing_issues = claim_fidelity_issues(
            "谐振腔的驻波条件为 nL=kλ/2。",
            ["谐振腔内会形成驻波，但本页公式未被文本提取器保留。"],
        )

        self.assertIn(
            "unsupported_relation",
            {issue.code for issue in missing_issues},
        )
        self.assertEqual(
            {issue.severity for issue in missing_issues},
            {"soft"},
        )
        self.assertEqual(
            hard_claim_fidelity_issues(
                "谐振腔的驻波条件为 nL=kλ/2。",
                ["谐振腔内会形成驻波，但本页公式未被文本提取器保留。"],
            ),
            (),
        )

        conflicting_issues = hard_claim_fidelity_issues(
            "谐振腔两端反射镜处为波节，满足 nkλ/2=L。",
            ["驻波条件为 nL=kλ/2（k=1,2,3,…）。"],
        )

        self.assertIn(
            "conflicting_relation",
            {issue.code for issue in conflicting_issues},
        )
        self.assertTrue(
            any(
                issue.fragment == "nkλ/2=l"
                and issue.severity == "hard"
                for issue in conflicting_issues
            )
        )

    def test_missing_number_is_soft_without_independent_contradiction(self):
        issues = claim_fidelity_issues(
            "He-Ne激光的波长为632.8nm。",
            ["本页说明He-Ne激光器的组成，但OCR没有提取波长。"],
        )

        self.assertIn(
            "unsupported_number",
            {issue.code for issue in issues},
        )
        self.assertEqual(
            hard_claim_fidelity_issues(
                "He-Ne激光的波长为632.8nm。",
                ["本页说明He-Ne激光器的组成，但OCR没有提取波长。"],
            ),
            (),
        )

    def test_extreme_dimensionful_value_without_unit_is_hard(self):
        definitions = (
            "He-Ne激光器的输出线宽可小到10^-15量级。",
            "He-Ne激光器输出线宽的数量级可小到10^-15。",
        )

        for definition in definitions:
            with self.subTest(definition=definition):
                hard_issues = hard_claim_fidelity_issues(
                    definition,
                    ["超高稳频时会小到10⁻¹⁵，为什么？"],
                )

                self.assertEqual(
                    [issue.code for issue in hard_issues],
                    ["extreme_scientific_value_missing_dimension"],
                )
                self.assertTrue(all(
                    issue.severity == "hard" for issue in hard_issues
                ))

    def test_protects_exact_and_algebraically_equivalent_relations(self):
        accepted = [
            ("能级满足 E_n=E_1/n²。", ["原文给出 Eₙ = E₁ / n²。"]),
            ("角动量满足 L_z=m_l ħ。", ["可写成 L_z = m_l ℏ。"]),
            (
                "相对线宽满足 Δν/ν≈10^-15。",
                ["超高稳频时 Δν / ν ≈ 10⁻¹⁵。"],
            ),
            ("激光波长为632.8nm。", ["He-Ne激光波长为 632.8 nm。"]),
            (
                "驻波条件也可写为 λ=2nL/k。",
                ["原文给出 nL=kλ/2。"],
            ),
        ]

        for definition, evidence in accepted:
            with self.subTest(definition=definition):
                self.assertEqual(
                    hard_claim_fidelity_issues(definition, evidence),
                    (),
                )

    def test_does_not_infer_hard_conflict_for_unparsed_additive_formula(self):
        issues = hard_claim_fidelity_issues(
            "定义给出 a=b/c。",
            ["相邻段落另有 a=b+c，但目标公式未被抽取。"],
        )

        self.assertEqual(issues, ())

    def test_real_poppler_subscripted_wavelength_exposes_hard_conflict(self):
        evidence_templates = (
            (
                "谐振腔驻波条件为 nL = kλ_k/2，"
                "等价地可写成 λ_k = 2nL/k。"
            ),
            (
                "谐振腔驻波条件为 nL = kλₖ/2，"
                "等价地可写成 λₖ = 2nL/k。"
            ),
        )

        for evidence in evidence_templates:
            with self.subTest(evidence=evidence):
                hard_issues = hard_claim_fidelity_issues(
                    "谐振腔驻波条件为 nkλ/2=L。",
                    [evidence],
                )

                self.assertIn(
                    "conflicting_relation",
                    {issue.code for issue in hard_issues},
                )

    def test_subscripted_wavelength_equivalent_rearrangement_is_not_hard(self):
        evidence_formulas = (
            "原式为 nL=kλ_k/2。",
            "原式为 nL=kλₖ/2。",
        )

        for evidence in evidence_formulas:
            with self.subTest(evidence=evidence):
                self.assertEqual(
                    hard_claim_fidelity_issues(
                        "驻波波长满足 λ_k=2nL/k。",
                        [evidence],
                    ),
                    (),
                )

    def test_different_base_or_nonempty_subscript_is_not_hard_matched(self):
        comparisons = (
            (
                "候选公式为 λ_j=2nL/k。",
                ["来源只给出 λ_k=2nL/k。"],
            ),
            (
                "候选公式为 ν_k=2nL/k。",
                ["来源只给出 λ_k=2nL/k。"],
            ),
        )

        for definition, evidence in comparisons:
            with self.subTest(definition=definition):
                self.assertEqual(
                    hard_claim_fidelity_issues(definition, evidence),
                    (),
                )


if __name__ == "__main__":
    unittest.main()
