# Visiomaster × 自动化交付管线优化方案（完整版）

> 版本：2026-08-28 v2。数据底座：C:\visio-worker\jobs 全量 58 单（30 max / 7 pro / 21 standard），26 单共 65+ 轮人工纠正语料（从时间戳 resume 日志全量恢复），18 份新版审查 subagent 结论（172 条发现）。
> 配套评测环境已搭建：`C:\visio-worker\eval\`（基准图、纠正清单、基线 skill 快照、runner 任务书、盲评表）。

---

## 0. 一页摘要

**诊断**：skill 仓库停在 2026-06-02（v0.3.1），而 6-8 月 58 单的实战教训没有回流。worker 三段提示词用的是一套自制通用审查 rubric，**没有调用 skill 已经建好的审查合同**（references/reviewer-two-image-prompt.md 里有结构化 checklist、region_scores、甚至 `_`/`^` 原始文本检查）。结果是审查员和用户的关注点错位：审查员报"字号小/间距松/变扁平"，用户纠"箭头几何/公式下标/换行/贴图政策"；修复后无复验，同类缺陷只修被点名的实例。

**方案**：五个支柱。
- P1 数据资产化：语料提取脚本 + 基准冻结（已建）+ 阶段文件追加式命名。
- P2 三段提示词重写：把 65 轮纠正变成"制图合同 + 七类审查分类学 + 修后复验"，并让 worker 审查对齐 skill 已有 review contract（含 crop 审查强制化）。
- P3 skill 门禁升级：4 个新确定性门禁（下标/换行、贴图政策、箭头微几何、同类清扫完整性）+ SKILL.md 规则回流。
- P4 平台修缮：状态回写、熔断、命名 bug、标准版跑门禁。
- P5 评测闭环：三层评测（L0 门禁单测 / L1 审查召回回归 / L2 全管线 A/B 盲评回放）+ 北极星指标。评测执行器用 ZCode subagent，不依赖 codex。

**北极星指标：人工纠偏轮次/单**（当前 65 轮/58 单 ≈ 1.12；目标先 <0.5，后 <0.2）。

---

## 1. 数据事实（为什么要这么改）

### 1.1 人工纠正聚类（65 轮）

| 类别 | 频次 | 典型原话 |
|---|---|---|
| A 箭头几何与连接 | 最高 | "箭头都断了""转角不够圆滑""有箭头超出了，尾部和头部都有""只有头没有横线""多了一部分你没发现吗" |
| B 公式/下标 | 高 | "很多公式还不是下标，是_""L_SPAN还是不是下标""分式现在不是" |
| E 贴图 vs 可编辑 | 5+ 单反复 | "是不是全是贴图？""方格图可以不用贴图吧，直接画出来？" |
| C 文字换行/拆字 | 中 | "128"拆成"12/8"、"FFN"拆成"FF/N" |
| F 布局/比例 | 中 | "整体大小和位置还是要修一下，和原图对齐" |
| G 立体块/颜色/朝向 | 中 | "纯纸片堆叠还是个歪的""方块朝向不一致" |

用户 3 次主动要求"用一个 subagent 审查"——Max 的 Stage 2 机制本身就是用户人工补出来的。

### 1.2 审查员实际报告（18 份 / 172 条）

- 严重 20% / 明显 53% / 轻微 27%；总体保真度 16/18 给"中"——评分尺度失效。
- 最高频：细节缺失（~65）、箭头连接（~50，40% 审查确认有端点/连接对象错误）、字号层级（~38）、间距留白（~38）、渐变阴影立体感（~32）。
- **错位实证**：贴图政策在用户投诉最重的 job 里审查命中 0；VM20260826072522912989 审查写"未发现箭头方向错误"，refine 后用户投诉的恰恰全是箭头。

### 1.3 三个结构性断裂

1. **感知分辨率**：审查员只看两张全图；用户是放大逐区域看的。
2. **单点 vs 同类**：refine 只修被点名实例，"修了一批，还有很多这种方格图"（连续两轮）。
3. **修复无验证**：refine 修完直接交付，无针对修改区域的复验。

### 1.4 运行资产盘点

- strict 管线在自动化里大部分真在跑：24-26/30 max 单落盘 scene.json + arrow_audit.json，13/30 有完整 review bundle，scene 单 job 迭代 4-9 版。
- review_findings.json 只有 8/30 落盘；4-5 单绕开 skill 管线自己写 win32com 脚本。
- 数据丢失：resume-prompt.txt 每轮覆盖、run-codex-*.ps1 被覆盖、run.log 截断；时间戳日志是唯一完整语料源。status 58/58 恒 running。VM20260724044609736409 自动续跑 30 轮零交付。存在 `resume-continue-continue-N` 命名 bug。
- codex 会话存档：874 个 rollout（5.3 GB），session id ↔ job 目录可互证。

---

## 2. 评测方案（先于优化实施定稿）

评测执行器：**ZCode subagent**（本机可跑完整管线：Read 源图 → 按 SKILL.md 生成 scene.json → 跑 skill 脚本 → Visio COM 渲染导出）。不用 codex，隔离更干净：每配置一份 skill 快照 + 一份 runner 任务书。

### 2.1 三层评测

| 层 | 测什么 | 需要什么 | 何时可跑 |
|---|---|---|---|
| L0 门禁单测 | 新门禁能否抓住植入缺陷 | 合成 scene.json 用例 | P3 实施时 |
| L1 审查召回回归 | 新旧审查 rubric 对"用户已确认缺陷"的召回率 | 历史图对 + 纠正清单，**零重新生成** | 立即可跑 |
| L2 全管线 A/B 回放 | BASE vs OPT 端到端效果 | OPT skill 快照 + runner 任务书 | P2+P3 实施后 |

### 2.2 L1 审查召回回归（先跑，最便宜）

1. 语料对：26 个被纠正 job 中，凡 review bundle 里有 `replica_roundN.png` / `replica_round*.png` 的（B1、B3 等都有），构造（源图, 中间版复刻图, 该时点之后的人工纠正项）三元组；没有中间版的用（源图, 最终 result.png, 最后一轮纠正项）。
2. 对每个图对分别跑两个干净审查 subagent：一个用现行生产 rubric（`eval\prompts\l1-review-BASE.md`），一个用新分类学 rubric（`l1-review-OPT.md`）。
3. 指标：召回率 = 审查发现覆盖到的纠正项数 / 纠正项总数；误报数 = 审查报告里对照源图不成立的项。
4. 判据：新 rubric 平均召回 ≥ 旧版 2 倍（现状估 <40% → 目标 >80%），误报不增加。
5. **结果（2026-08-30，已通过）**：3 图对 6 次盲审完成，P1 召回 17%→83%（旧版在用户纠了 8 轮的图上判"保真度高、无箭头错误"，新版抓到 ∫ 喂线拓扑错误与方格贴图违规）、P2 67%→92%、P3 持平 100%（新版多同类清扫计数）；未见 OPT 误报增加；OPT token 成本约 2-2.6 倍。详见 `C:\visio-worker\eval\results\l1_report.md`。

### 2.3 L2 全管线 A/B 回放（用户拍板的协议）

- 基准图：B1（VM20260721163734626299，8 轮）、B2（VM20260818091147685645，4 轮）、B3（VM20260727170616750219，4 轮），B4（VM20260606182136176275，公式/箭头双灾）为可选。每张图带 `correction_checklist.md`（逐项来自真实纠正语料）。
- 矩阵：每图 × {BASE, OPT} × 2 轮 = 12 run（B4 可选 +4）。BASE 用冻结快照 `eval\skills\visiomaster-baseline-20260828`，OPT 用实施后的 `eval\skills\visiomaster-optimized`。
- 执行：`eval\prompts\runner-BASE.md` / `runner-OPT.md`（自包含，替换三个占位符），交给全新后台 subagent。建议先跑 B1 的 4 run 作 pilot。
- 盲评：结果 PNG 随机码匿名（`results\`），用户按 `eval\scoring\blind_scoring_sheet.md` 逐项判 checklist 复发 + 七类新增缺陷数 + 0-10 分 + 可交付 y/n；评完再开 `unblind_key.json`。
- 判据（评分前锁定）：
  - M1 纠正复发数（两轮合计）：OPT < BASE，全部基准图；
  - M2 盲评可交付率：OPT ≥ BASE；
  - M3 新增严重拓扑错误（A 类）：OPT = 0；
  - M4 门禁拦截数：只记录。
  - 任一不满足 → 读 OPT 的门禁输出与 review_findings.json 定位漏检原因，修订后只重跑不达标图。
- 成本：单 run ≈ 1-3 小时、数十万 token；全矩阵 ≈ 1-1.5 天机器时间（2 路并行），pilot 半天。
- 统计诚实性声明：2 轮/配置只做方向性判定（ go/no-go ），不是显著性检验；持续验证靠 P5 的产线指标。

### 2.4 已就位的评测资产

```
C:\visio-worker\eval\
├── benchmark\B1..B4\        源图 + reference_result.png + correction_checklist.md
├── skills\visiomaster-baseline-20260828\   BASE 冻结快照（9 MB，v0.3.1）
├── prompts\runner-BASE.md   BASE 运行任务书（现行提示词原文）
├── prompts\runner-OPT.md    OPT 运行任务书（新提示词，P2/P3 完成后可执行）
├── prompts\l1-review-BASE.md / l1-review-OPT.md   L1 两个 rubric
├── scoring\README.md        运行矩阵 + 盲评流程 + 锁定判据
├── scoring\blind_scoring_sheet.md
├── runs\  results\          运行与匿名结果目录
```

---

## 3. P1 语料资产化

1. `scripts/extract_worker_corpus.py`（本仓库新增）：扫 `C:\visio-worker\jobs\*`，产出 `corpus/manifest.jsonl`（job id、product_type、session_id、rollout 路径、阶段日志路径、全部 resume 轮次原文+时间戳、审查结论原文、三件套齐全性、resume 轮数）。解析需兼容 `resume-continue-continue-N` 命名。
2. `scripts/build_defect_taxonomy.py`：把纠正 + 审查发现映射到七类分类（A 箭头 / B 公式 / C 文字 / D 缺失多余 / E 贴图 / F 布局 / G 风格），输出 `corpus/defect_taxonomy.json`——它是 Stage 2 rubric、门禁阈值和 L1 评分的共同上游。之后每 ~20 单增量重跑。
3. 基准冻结：已完成（`eval\benchmark\`）。
4. 止血：worker 阶段文件改追加式命名（见 §8）。

---

## 4. P2 三段提示词重写（改动点 = Start-VisioWorker.ps1 的 5 个函数）

> 原则：每条要求都对应真实纠正语料；worker 审查对齐 skill 已有 review contract，不另造格式；skill 侧 `references/reviewer-two-image-prompt.md` 同步补 E 类与同类清扫条款，两边措辞来自同一份 `defect_taxonomy.json`。

### 4.1 New-FirstPrompt v2（追加"制图合同"段，保留原输出路径约束）

```text
制图要求（必须遵守）：
1. 走 visiomaster skill 的完整 strict 管线：先做 source_visual_inventory 与 arrow_plan，
   再以源像素坐标系 authoring scene.json；不要绕开 scene.json 直接用 win32com 画图。
2. 贴图政策：仅照片、复杂位图、手绘纹理允许 image_tile，且每个贴图必须登记
   justification 与 source_bbox_px；方格图、矩阵、色块堆叠、legend 样例、简单图标、
   流程框、箭头等一切几何/规则图形必须用可编辑组件重画，禁止截图代替。
3. 所有公式下标/上标用 math_text fragments 渲染；画面文本禁止出现原始 "_"、"^"；
   源图单行标签禁止换行（显式 no-wrap），禁止为容纳文字放大整个模块。
4. 渲染后依次运行并通过：scene_validate --strict、arrow_audit_gate --strict、
   style_calibration_gate --strict、scene_geometry_assert --strict、
   scene_audit --fail-on-rebuild、text_render_audit、raster_policy_audit。
   任一门禁不过，先修 scene 再交付，不许跳过。
5. 交付前对照源图逐区域放大自查：每条箭头起点终点接触目标边界、无只带箭头头的短线、
   无出头线段、无穿过文字的线；抽查 3 个公式区域和 3 个小字区域。
```

依据：第 1 条治 4-5 单绕开管线；第 2 条治 B1-E1/E2、B2-E1、B3-E1；第 3 条治 B4-B1/B2、"12/8"；第 4-5 条治 B1-A1~A3、B4-A1/A2 这类微几何。

### 4.2 New-CleanReviewTask v3（七类分类学 + 同类清扫 + JSON 落盘）

```text
你是独立的 Visio 复刻视觉审查员。只做只读视觉对比，不修改文件、不创建审查文件、
不创建其他 subagent。你会收到两张全图、最多 6 对区域 crop 对、以及 arrow_audit.json
的边清单（源图事实清单，不是制图结论）。crop 对只用于放大确认，结论以两张全图为锚。

按以下七类逐类扫过全图，每类必须给出"发现问题数"，为 0 也要明说：
A. 箭头与连接（最高优先级，逐条对照边清单）：端点是否接触目标边界、断线/悬空、
   出头越过目标、方向与原图一致性、拐弯处多余凸出段、只画箭头头没有线身、多条箭头重叠。
B. 公式与下标：下标渲染成 "_" 或散落字母、分式缺分数线、公式换行、上下标方向。
C. 文字完整性：源图单行标签换行、文字被拆开、文字与图形重叠。
D. 缺失与多余：源图有而复刻没有的元素（含面板内小元素、内部横线、小箭头）；
   复刻有而源图没有的元素。
E. 贴图政策：逐个检查疑似贴图区域；方格图/色块堆叠/矩阵/简单图标类内容若为贴图即违规，
   点名要求重画为可编辑组件。
F. 布局与比例：模块位置、相对大小、留白与原图一致性。
G. 风格：颜色、字体层级、圆角、阴影、立体感。

同类缺陷必须全页清扫：发现一个实例后，明确回答"全页同类还有几处"并列出位置。
最多报告 20 个问题；A 类不受限制，逐条全报。
每个问题格式：严重程度（破坏拓扑或语义=严重 / 明显可视=明显 / 轻微）、位置、
原图表现、当前差异、明确修改建议。
同时输出 JSON（对齐 visiomaster review_findings schema：findings + topology_checklist
+ visual_checklist + region_scores），总体保真度锚定：
低=有拓扑/箭头方向/公式语义错误；中=多处明显可视差异；高=仅剩轻微风格差异。
最后给出：必须优先修复的三个问题、A 类结论
（无问题 / 端点 n 处 / 方向 n 处 / 断线 n 处 / 出头 n 处）。
```

### 4.3 New-ReviewPrompt v2（crop 强制 + 边清单随附 + findings 落盘）

在现有"创建干净 subagent、原样转交任务"骨架上追加三句：
1. "派发前，先用 skill 的 make_review_assets.py 按 arrow_plan/region_plan 选取 arrow-dense、formula、small-text 区域生成源图/复刻图 crop 对（最多 6 对），连同两张全图、arrow_audit.json 边清单一起交给 subagent。"
2. "subagent 只读图，不写文件；返回后由你把完整结论写入 <job>\review_findings.json（对齐 review_findings schema），下一阶段会用它。"
3. "如果 skill 的 make_review_assets 或 arrow_audit.json 不存在，如实说明并仅用两张全图审查，禁止伪造清单。"

依据：审查员只看全图 → 小字/微箭头不可见（§1.3 断裂 1）；落盘治 8/30 持久化率。

### 4.4 New-RefinePrompt v2（修一类、验一类、证明改过）

```text
根据审查结论精修，执行顺序：
1. 先修"严重"，再修"明显"；同类问题全页一次修完（结论里写了同类还有 n 处的全部处理），
   不要只修被点名的实例。
2. 每修完一类，重新渲染后对该类涉及区域生成 crop 与原图同区域对比，确认修复后
   才进入下一类。
3. 修复只改对应局部；不要无关重构，不要重新设计原图。修改连接时同时确认起点、
   终点和箭头方向。
4. 交付前用 skill 的 round_noop_gate.py 证明本轮 scene/渲染确实变化；把
   review_findings.json、arrow_audit.json 和门禁输出留在 job 目录供后台检验。
5. 必须直接覆盖原来的三个文件，不要新命名，不要输出到其它目录；
   完成前确认三个文件都存在且非空。
```

依据：§1.3 断裂 2、3（B1"还有很多这种方格图"、B2 箭头投诉在 review 通过后仍发生）。

### 4.5 New-RerunPrompt v2（人工补充 Prompt 也走同一套动作）

追加一段："把下面的补充要求当作一条审查发现处理：先定位涉及的局部区域并生成 crop 对确认问题，再修复，再扫描全页同类缺陷一并修复，最后对该区域复验。保持已正确模块稳定。" 依据：现在 rerun 只是把用户的话原样丢回会话，没有动作结构。

### 4.6 同步修改（skill 侧）

- `references/reviewer-two-image-prompt.md`：输入合同里"一或两个 crop 对"放宽为"至多 6 对由编排者生成的 crop 对"；Focus 列表加 E 类贴图政策；Output Rules 要求 findings 带 `class_id`（A-G）、`similar_instance_count`、`similar_locations`。
- `references/review-contract.md` 同步 class_id 字段。
- 新增 `references/defect-taxonomy.md`：七类定义 + 每类的可确认判据（两侧共享上游）。

---

## 5. P3 门禁规格（skill 代码工作）

### 5.1 text_render_audit.py（新）

- CLI：`python text_render_audit.py <scene.json> [--strict]`，输出 JSON 缺陷清单，--strict 时缺陷即非零退出码。
- 规则：
  - R1 任何节点/边标签 text 含原始 `_`/`^` → fail（除非带 `source_underscore_ok: true` 豁免标记，且 source inventory 能证明源图本身显示下划线字符）；
  - R2 疑似数学标签（正则 `[A-Za-z]_[A-Za-z0-9]+`、已知数学记号）未用 `math_text`/`math_vector`/fragments → strict 下 fail；
  - R3 声明 `single_line: true` 的标签，按字数×字号×字宽系数估算文本宽 > 框宽 → fail（防"12/8"拆字）；
  - R4 有 `container_id` 的文本节点 bbox 超出容器 → fail。
- 单测：植入 `L_SPAN` 裸文本 → 必须 flag；math_text fragments → pass；窄框长单行标签 → 必须 flag。

### 5.2 raster_policy_audit.py（新）

- CLI 同上。
- 规则：
  - R1 每个 raster 节点必须有 `justification` ∈ {photographic, complex_bitmap, source_unreadable_otherwise} 且有 `source_bbox_px`，缺失 → fail；
  - R2 区域角色/命名为 grid/matrix/cell_strip/legend_sample/simple_icon 的贴图 → 无条件 fail（永远可重画）；
  - R3 raster 总面积占页面 >8% → warn，>15% → strict fail。
- 单测：无 justification 的 image_tile → fail；有 justification 的照片 tile → pass；带 justification 的方格图 tile → 仍 fail。

### 5.3 箭头微几何（扩展 arrow_audit_gate.py + scene_geometry_assert.py）

现有已覆盖：dangling tiny fragment、无箭头线带头、模板轴向、smooth/bezier 误用、路线穿越禁越节点、endpoint_must_touch/target_boundary。新增：
- R5 `endpoint_overshoot`：有 geometry_contract 的边，终点超出目标 bbox > max(2px, 0.15×head_length) → fail（治"超出了，尾部和头部都有"）；
- R6 `head_only_fragment`：末段直线长度 < 1.5×head_length → fail（治"只有头没有横线"）；
- R7 `corner_spur`：正交路线出现偏离主方向 < corner_radius 的多余短拐 → warn（治"拐角多了一截/凸出去"）；
- R8 圆角保真：style_calibration 声明圆角转角而边缺 `corner_radius_px` → warn。
- 单测：植入 overshoot / head-only / spur 三种边 → 必须 flag；正常圆角正交边 → pass。

### 5.4 同类清扫完整性（扩展 review_checklist_gate.py）

- findings 的每条 finding 可带 `class_id`（A-G）+ `similar_instance_count` + `similar_locations`；
- --strict 下：finding 缺 class_id、或 class_id 非 null 而 similar_instance_count 缺失、或 E 类 finding 无逐 tile 清单 → 判 incomplete，gate fail。
- 单测：三条 findings 无 sweep 字段 → fail；带完整字段 → pass。

### 5.5 SKILL.md 规则回流（追加为规则 91-98，可粘贴）

```text
91. 贴图政策：一切几何/规则图形（方格图、矩阵、色块堆叠、legend 样例、简单图标、
    流程框、箭头）必须可编辑重画。image_tile 仅用于照片、复杂位图、手绘纹理，
    每个 tile 必须登记 justification 与 source_bbox_px；raster 面积占比超过 8%
    必须在交付说明中解释。运行 raster_policy_audit.py 强制。
92. 下标与换行：画面文本禁止出现原始 "_"、"^"；词形下标一律 math_text fragments；
    源图单行标签必须显式 no-wrap，禁止为容纳文字放大整个模块。运行 text_render_audit.py。
93. 箭头微几何合同：交付前每条边自查端点接触、无 overshoot、无 head-only 残段、
    圆角与源一致；由 arrow_audit_gate / scene_geometry_assert 扩展检查强制。
94. 同类清扫：审查发现任何缺陷实例后，必须全页扫描同类并在 findings 中报告
    similar_instance_count 与位置清单；修复时一次修完全部同类。
95. 修后复验：refine 每修完一类，必须对该类区域重新生成 crop 对与源图对比确认；
    未复验不得宣称修复完成。
96. 审查分辨率：arrow_dense、formula、small_text 区域必须以 crop 对审查；
    禁止只凭全图判断 A/B/C 类缺陷。
97. 结论持久化：每轮审查结论必须由主会话落盘 review_findings.json；缺失视为流程违规。
98. 完成定义：strict 模式交付 = 全部门禁绿 + round_noop_gate 通过 + 三件套非空。
```

### 5.6 其他 skill 改动

- `make_review_assets.py` 加 `--from-arrow-audit`：按边密集度自动选 crop 区域（降低 Stage 2 调用门槛）。
- 把人工验收通过的成品 scene 清洗后收进 `templates/examples/paper_figures/`（B1、B3 的最终 scene.json 优先）。

---

## 6. P4 平台/worker 修缮（visio-order-platform 仓库）

1. status 回写：阶段完成/失败/人工验收后更新（改 worker 上报与后端 `worker.go` 对应处理；现状 58/58 恒 running）。
2. 阶段文件追加式：`Save-JobFiles` / `Invoke-CodexStage` 中 `"$stageName-prompt.txt"` 改为 `"$stageName-<yyyyMMdd-HHmmss>-prompt.txt"`；run-codex-*.ps1 同理加时间戳。
3. 熔断：`Invoke-GenerationStage` 续跑循环里，连续 N=4 轮三件套 hash 无变化 → 写诊断并以失败退出，不再 continue（VM20260724044609736409 烧 30 轮教训）。
4. 修 `resume-continue-continue-N` 字符串拼接 bug（续跑轮次基于基础阶段名拼接）。
5. 标准版/Pro 版也跑确定性门禁：门禁是本地脚本零 API 成本。standard 至少 scene_validate --strict + 新两门禁；pro 加 arrow_audit_gate。Get-ProductStages 的阶段产出检查（Test-ResultsReady 旁）增加"job 根目录必须存在 scene.json"工件检查，防绕开管线。

---

## 7. P5 例常回流

- 每 ~20 单：重跑 extract + taxonomy 增量 → 更新 rubric 措辞/门禁阈值 → 跑一轮 L1 回归 → 必要时补 L2 单图 pilot。
- 产线指标看板：纠偏轮次/单、Stage 2 对人工发现召回率、门禁拦截数、同类清扫完成率、单均时长。
- skill 版本与语料版本对齐：每次 rubric/门禁变更 = 一次 workcopy 提交 + sync + 新 eval 快照。

---

## 8. 实施顺序

| 周 | 内容 | 产出 |
|---|---|---|
| 第 1 周 | P1 脚本 + L1 回归（现在就能跑）+ P2 提示词上线 | 召回率对比报告；新三段提示词进 worker |
| 第 2 周 | P3 四门禁 + 单测 + SKILL.md 规则 91-98 + reviewer prompt 同步 | v0.4 skill；L0 全绿 |
| 第 3 周 | OPT 快照 → L2 pilot（B1 × 4 run）→ 盲评 → 全矩阵 | A/B 盲评报告与 go/no-go |
| 第 4 周 | P4 平台修缮 + 产线指标看板 | 修缮上线 |

风险：审查 rubric 变严可能增加单均时长（crop 复验、同类清扫）；用 L2 记录时长增幅，超 50% 再裁剪 crop 数量。门禁误报会变噪声——L0 单测 + L1 误报数双控。新提示词只影响新单；旧单不回刷（skill 自己的 fresh-evaluation 原则）。
