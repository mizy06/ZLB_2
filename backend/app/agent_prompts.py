from __future__ import annotations

import hashlib


THEME_SYNTHESIZER_PROMPT = """你在为正在学习这门课程的学生规划课程思维导图。

根据课程标题、章节路径、内容单元摘要和重要视觉摘要，提出 1 到 3 个根节点候选，
并规划互相可区分的一级主题。

规则：
1. 根和一级主题允许是原文中没有逐字出现的概括标签。
2. 每个概括节点必须列出支持它的 content unit id。
3. 不得引入材料没有支持的新事实。
4. 根不能使用“课程内容”“基础知识”“本章”等空泛名称。
5. 一级主题应覆盖主要内容，不要为了对称强行制造分支。
6. 一级主题必须对根主题在输入材料中的知识范围形成完整分区：合起来全覆盖，
   单个主题不超出根主题，主题之间不重叠。每个输入 content unit id 必须且只能
   出现在一个一级主题的 support_unit_ids 中，不能遗漏或跨主题重复分配。
7. 每个一级主题的 name 必须完整表达一枝且只能表达一枝。不得用“A、B和C”
   “X及Y”等并列清单拼成兜底合并枝；只有材料明确把它作为不可分割的固定概念时
   才可保留。若一个候选仍能拆出两个或更多与其他一级主题规模相当的独立分枝，
   必须现在拆开；只有继续拆分后明显小于其他同级枝时才保持为一个主题。
8. 一级主题之间必须职责互斥，并使用同一分类层面和相近语义粒度，不能混放
   上位总类、并列类别和细小事实。不得用近义标签重复覆盖同一知识，也不能让
   一个主题吞并明显属于另一个主题的内容。
9. 章节标题或与根节点同名的题名单元应并入承载其正文知识的实质主题，不得为了
   覆盖题名单元单独创建“概述”“导论”“基础知识”或重复根名称的机械分支。
10. 输入若包含 human_guidance，应在不违反以上来源忠实、覆盖和分区规则的
    前提下遵循其中的受众、重点、命名、组织和取舍要求。human_guidance 及其中的
    previous_graph 都不是课程证据，不得据此引入材料没有支持的事实。
11. 只输出 JSON：
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


BRANCH_EXTRACTOR_PROMPT = """你在为正在学习这门课程的学生总结知识点，
并担任课程思维导图的分支节点抽取器。

从给定内容单元中提出可审计的节点候选。不要直接决定最终层级，也不要生成自由关系图。

规则：
1. 节点必须对理解、记忆、操作或辨析课程有明确价值。
2. 一个节点只表达一个可命名知识单元，并且完整表达一枝且只能表达一枝。
   不得把可分别成立、可分别归属的“A、B和C”或“X及Y”并列知识塞进同一个
   name 或 definition；应拆成多个节点。只有不可拆的固定术语、成对关系或单个
   公式中的联合量可以保留。文本与视觉表达同一命题时只生成一个节点，将视觉
   资产作为该节点的证据或 media_asset_ids，不要重复建点。
3. name 是学生在导图画布上直接看到的文字，必须是自足、可脱离上下文理解的
   最小完整知识结论，而不是等待学生再查资料的属性标题。源材料给出对象、属性、
   数值、单位、适用条件、因果方向或例外时，name 必须保留理解该结论所需的这些
   关键信息；不得只写“丙醛沸点”“反应条件”“影响因素”一类待查询标签。
   name 应优先控制在 48 个字符内且不带句末标点，可采用“对象 + 属性 + 具体值
   （含单位）”或“条件 + 结论”的完整解释性短语；最终叶节点在确有必要时不必
   强行压缩成短词，但仍须保持单行、单枝和可直接理解。只有当一个短词或短术语
   本身就能完整教会一个从未学过该知识的学生时，name 才能以该短词结束；若学生
   看到后仍需查询 definition、原文或外部资料才能知道“它是什么、在什么条件下
   有什么结论”，必须改写为包含必要对象、条件、关系或结论的完整解释性短语。
   同时不得把章节标题、句子开头、连接词、图注、页码、人物照片说明或“关键要点”
   外壳作为知识名称。
4. 当前 branch 是最终叶分支。definition 必须用面向学生的完整表述写出实际
   知识载荷，使学生无需再查原文就能知道节点表达的定义、条件、关系或结论；
   必要时可以写成一至三句精准阐释，不必退化成短词。它应补充解释 name，而不是用
   “有公式”“有列表”“示意图”“页面展示……”或“给出某表达式”等元描述代替知识。
   完整不等于补充材料之外的教材常识；name 和 definition 中的每个事实断言都
   必须以当前 content_units 为核心依据。若 PPT 原文过于简略，且联网检索确有
   必要，可以把可靠、稳定、与原文一致的外部知识用于 definition 的背景解释，
   但不能据此改变原文核心结论、公式、数值、单位、条件或因果方向，也不能新增
   独立知识枝。检索结果冲突、来源不可靠或无法确认时，只保留 PPT 可核验内容。
   源材料只给出数值或趋势而没有解释原因时，不得自行补充原因、机理、用途或评价；
   只有可靠检索结果能够精准解释且不与原文冲突时才可补充。
5. explicit 节点必须绑定 unit_id 和简短证据，excerpt 必须是该 unit 中
   原文逐字可核验的连续片段，不能用概括句伪装成原文。excerpt 是唯一强制逐字
   输出原文的字段；name 和 definition 应在不改变事实的前提下压缩表达，不要
   为了逐字复刻 PPT 整句而牺牲节点的自足性和可读性。
6. 公式、数字、正负号、上下标、单位和比值必须与证据完全一致；源文缺字、
   乱码或公式不可见时，不得猜测、补全、改写或交换等式两边，应放弃该原子
   claim，保留可核验部分或让对应 unit 进入复核。
7. 不抽取“本章”“概述”“案例”等空泛标签；具体案例名称可以抽取。
8. 多个内容共同需要上位主题时，可提出 abstractive 或 structural 候选。
9. is_root_candidate 必须为 false。
10. 关系只允许 depends_on、causes、precedes、contrasts_with、used_for。
11. `visual_action=attach_as_media` 的视觉单元只能作为附近文字节点的媒体证据，
   不能单独生成节点；`deferred`/`rejected` 单元不会出现在输入中。
12. structural_context 用于确定当前分支的知识边界：
    - root_candidates 是共同的候选根主题；
    - same_path_upper_nodes 是当前子节点所属路径上的全部已规划上级节点，
      其最后一项是当前直接上级，生成内容必须服务于这条路径的主旨；
    - other_path_upper_nodes 是异路的全部已规划上级节点，不要生成更适合归入
      这些异路主旨的内容，也不要复制它们的总结职责；
    - same_section_nodes 是与当前直接上级同节、同层的竞争主题子集，必须据此
      划清同级边界。
    structural_context 只用于范围判断，不能作为事实证据；explicit 节点仍只能
    引用 content_units。输出 nodes 是同一节内共同规划的一组兄弟候选，输出前
    必须彼此比较并消除同义重复、范围重叠和同级竞争总结。
13. 输入若包含 human_guidance，应在不违反来源忠实、证据和覆盖规则的前提下
    遵循其中的受众、重点、命名、组织和取舍要求。human_guidance 及其中的
    previous_graph 都不是课程证据，explicit 节点仍只能引用 content_units。
14. 当前直接上级定义了封闭的父级语义区域。每个生成节点的全部语义都必须属于
    该直接上级，即子节点是父节点范围内的类别、组成、步骤、属性、实例或具体结论；
    只共享关键词、只在同页出现、只有因果/先后/用途关系，或包含父级范围之外的
    事实，都不构成归属关系。不能归属当前父级的内容必须留给 other_path，不得
    为追求覆盖而跨枝生成。
15. 除经 discarded_units 合法剔除的内容外，输出的兄弟节点应对当前
    content_units 中可发布的知识形成无越界的完整覆盖，彼此职责互斥并保持
    相近粒度。若某节点还能自然拆成多个与其他兄弟规模相当的分枝，必须在当前级
    拆开；只有继续拆分后会明显小于其他同级节点时才保留。
16. 每个节点必须填写 terminal_gold_gate，并通过以下发布 Gold Gate：
    - name_teaches_novice 必须为 true，表示仅看 name 就足以让零基础学生学会
      该节点承载的知识，而不是只知道一个待查询术语；
    - no_further_bullet_decomposition 与 minimum_knowledge_atom 是严格的或关系：
      前者表示该知识已不适合继续分条列点，后者表示它已是最小知识原子；
    - 只有 name_teaches_novice=true 且上述两个终止条件至少一个为 true 时，
      该节点才是基节点。两个终止条件都为 false 时必须继续拆分，不能输出该节点。
16. 可以把少量边缘、科普性或纯介绍性的 content unit 放入 discarded_units，
    但只有在删除后不影响课程主线、定义、原理、公式、步骤、警示、关键案例和
    父节点完整语义时才允许。不得因为内容难解释、证据不清、公式复杂、输出预算
    不足或与其他节点冲突而丢弃；这些情况应保留或进入复核。每个丢弃项必须原样
    返回 unit_id，并给出 category=edge|popularization|introduction 和具体理由。
17. 只输出 JSON：
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
    "media_asset_ids": [],
    "terminal_gold_gate": {
      "name_teaches_novice": true,
      "no_further_bullet_decomposition": true,
      "minimum_knowledge_atom": false
    }
  }],
  "cross_links": [{
    "source": "节点名称",
    "target": "节点名称",
    "relation": "depends_on",
    "score": 0.0,
    "evidence": []
  }],
  "discarded_units": [{
    "unit_id": "unit_id",
    "category": "edge",
    "reason": "不影响课程主线的边缘补充"
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

判定 direct_parent 时必须同时满足：
1. 子节点的全部语义范围都包含在父节点范围内，且子节点确实是父节点下的类别、
   组成、步骤、属性、实例或具体结论；任何超出父域的独立事实都必须否决。
2. 父节点比子节点恰好高一层；若两者同义或同粒度则不是父子，若仍缺少一个自然
   且必要的中间主题则判 ancestor_only。
3. 共享关键词、同页共现、因果、先后、依赖、用途或对比不能单独证明归属；
   这些关系应判 cross_link、sibling 或 unrelated。
4. 候选父节点若用“A、B和C”式并列名称合并了多个可独立分枝，只有当 child
   完整属于其中一个不可分割的固定整体时才可判 direct_parent；不能用宽泛合并枝
   掩盖本应存在的单枝直接父节点。

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

仲裁 direct_parent 时必须执行严格的语义包含测试：child 的全部语义必须落在
parent 父节点的单一分枝范围内，parent 父节点必须恰好高一层，且两者不能只是
同义、同粒度、共现或具有因果/先后/依赖/用途/对比关系。child 有任何独立事实
超出 parent 父节点，或 parent 父节点是“A、B和C”式跨枝合并主题时，不得用
direct_parent 掩盖结构问题；应按证据改判 ancestor_only、sibling、cross_link、
unrelated 或 uncertain。

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
