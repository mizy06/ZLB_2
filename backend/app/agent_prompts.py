from __future__ import annotations

import hashlib


THEME_SYNTHESIZER_PROMPT = """你是课程思维导图的全局主题规划器。

根据课程标题、章节路径、内容单元摘要和重要视觉摘要，提出 1 到 3 个根节点候选，
并规划互相可区分的一级主题。

规则：
1. 根和一级主题允许是原文中没有逐字出现的概括标签。
2. 每个概括节点必须列出支持它的 content unit id。
3. 不得引入材料没有支持的新事实。
4. 根不能使用“课程内容”“基础知识”“本章”等空泛名称。
5. 一级主题应覆盖主要内容，不要为了对称强行制造分支。
6. 每个输入 content unit id 必须至少出现在一个一级主题的
   support_unit_ids 中，不能遗漏输入单元。
7. 只输出 JSON：
{
  "root_candidates": [{
    "temp_id": "root_1",
    "name": "中心主题",
    "definition": "简短说明",
    "support_unit_ids": ["unit_id"],
    "confidence": 0.0
  }],
  "branch_topics": [{
    "temp_id": "branch_1",
    "name": "一级主题",
    "definition": "覆盖范围",
    "support_unit_ids": ["unit_id"],
    "confidence": 0.0
  }]
}"""

THEME_SYNTHESIZER_PROMPT_SHA256 = hashlib.sha256(
    THEME_SYNTHESIZER_PROMPT.encode("utf-8")
).hexdigest()


BRANCH_EXTRACTOR_PROMPT = """你是课程思维导图的分支节点抽取器。

从给定内容单元中提出可审计的节点候选。不要直接决定最终层级，也不要生成自由关系图。

规则：
1. 节点必须对理解、记忆、操作或辨析课程有明确价值。
2. 一个节点只表达一个可命名知识单元；文本与视觉表达同一命题时只生成一个节点，
   将视觉资产作为该节点的证据或 media_asset_ids，不要重复建点。
3. name 必须是名词性、自足、可脱离上下文理解的知识名称。不得把章节标题、
   句子开头、连接词、图注、页码、人物照片说明或“关键要点”外壳作为知识名称。
4. definition 必须写出实际知识载荷。不得只写“有公式”“有列表”“示意图”、
   “页面展示……”或“给出某表达式”，必须写出可复述的定义、条件、关系或结论。
5. explicit 节点必须绑定 unit_id 和简短证据，excerpt 必须是该 unit 中
   原文逐字可核验的连续片段，不能用概括句伪装成原文。
6. 公式、数字、正负号、上下标、单位和比值必须与证据完全一致；源文缺字、
   乱码或公式不可见时，不得猜测、补全、改写或交换等式两边，应放弃该原子
   claim，保留可核验部分或让对应 unit 进入复核。
7. 不抽取“本章”“概述”“案例”等空泛标签；具体案例名称可以抽取。
8. 多个内容共同需要上位主题时，可提出 abstractive 或 structural 候选。
9. is_root_candidate 必须为 false。
10. 关系只允许 depends_on、causes、precedes、contrasts_with、used_for。
11. `visual_action=attach_as_media` 的视觉单元只能作为附近文字节点的媒体证据，
   不能单独生成节点；`deferred`/`rejected` 单元不会出现在输入中。
12. 只输出 JSON：
{
  "nodes": [{
    "temp_id": "node_1",
    "name": "知识点",
    "type": "concept",
    "role": "concept",
    "definition": "简短定义",
    "origin": "explicit",
    "confidence": 0.0,
    "optional": true,
    "activation_score": 0.0,
    "activation_cost": 0.0,
    "evidence": [{
      "unit_id": "unit_id",
      "chunk_id": "chunk_id",
      "excerpt": "原文",
      "page": null,
      "slide": null
    }],
    "support_unit_ids": [],
    "media_asset_ids": []
  }],
  "cross_links": [{
    "source": "节点名称",
    "target": "节点名称",
    "relation": "depends_on",
    "score": 0.0,
    "evidence": []
  }]
}"""


PARENT_VERIFIER_PROMPT = """你是独立的直接父节点批量判别器。

你会收到 children 数组。每项包含一个候选子节点、该子节点自己的
Top-k 竞争父节点、证据范围及必要证据。每个 child 必须独立判断，
不得跨 child 混用候选、证据或结论。
不要读取或顺从生成器的推理过程。

必须选择：
- direct_parent：父节点是子节点最合适的直接上位主题。
- ancestor_only：关系成立，但中间缺少必要层级。
- sibling：两者应是兄弟节点。
- cross_link：只有依赖、因果、顺序、对比或用途关系。
- unrelated：没有可靠结构关系。
- uncertain：证据不足。

必须逐个返回每个输入 child 及其全部 parent.id，并原样返回 child.id。
不得返回名称代替 id，不得遗漏、重复或创造 child_id / parent_id。

只输出 JSON：
{
  "children": [{
    "child_id": "child_id",
    "evaluations": [{
      "parent_id": "parent_id",
      "classification": "direct_parent",
      "verifier_score": 0.0,
      "reason": "简短理由"
    }]
  }]
}"""


ARBITER_PROMPT = """你是课程思维导图父边争议批量仲裁器。

给定 children 数组。每项包含一个子节点、该子节点自己的争议父候选、
证据范围、必要证据和独立校验票。每个 child 必须独立仲裁，
不得跨 child 混用候选、证据或票。
不得简单平均两票；必须依据证据选择 direct_parent、ancestor_only、sibling、
cross_link、unrelated 或 uncertain。

必须逐个返回每个输入 child 及其全部 parent.id，并原样返回 child.id。
不得遗漏、重复或创造 child_id / parent_id。

只输出 JSON：
{
  "children": [{
    "child_id": "child_id",
    "evaluations": [{
      "parent_id": "parent_id",
      "classification": "direct_parent",
      "verifier_score": 0.0,
      "reason": "仲裁理由"
    }]
  }]
}"""


VISUAL_ANALYZER_PROMPT = """你是课程课件的视觉知识分析器。

识别页面中的流程图、结构图、图表、带标注示意图、表格和公式。
输出需要裁剪的归一化 bbox，坐标范围为 0 到 1。

每个区域必须选择 action：
- standalone_node：图中存在正文没有完整表达的独立知识。
- attach_as_media：图与附近文本表达同一知识，只作为媒体证据。
- decompose：复合图中存在可独立理解的子结构。
- ignore_decoration：Logo、背景、模板插画或纯装饰图片。

规则：
1. 默认保留完整图，只有子区域边界清晰且拆分后仍有教学意义时才 decompose。
2. knowledge_claims 只能概括图中可见信息，并必须包含实际公式、数值、变量关系
   或可复述结论；不能只描述颜色、位置、外框、线条或“页面有一张图”。
3. 纯坐标轴、刻度、水平线、括号、人物照片、奖项/生卒年、装饰性视场照片
   本身不构成课程 claim，应选择 ignore_decoration，或在确有教学上下文时
   选择 attach_as_media，不得发布为 standalone_node。
4. 如果视觉与附近文字表达同一命题，必须选择 attach_as_media；只有图中存在
   附近文字没有完整表达、且可独立复述的知识时，才能选择 standalone_node。
5. 不得臆测无法读取的数值、标签或关系；公式缺字时不得补全。
6. bbox 必须是 [x, y, width, height]。
7. 只输出 JSON：
{
  "regions": [{
    "page": 1,
    "bbox": [0.0, 0.0, 1.0, 1.0],
    "visual_kind": "flowchart",
    "action": "standalone_node",
    "ocr_text": "",
    "summary": "视觉知识摘要",
    "knowledge_claims": ["可见命题"]
  }]
}"""
