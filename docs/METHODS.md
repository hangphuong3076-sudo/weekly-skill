# METHODS — weekly-skill 方法说明（v2.2.0）

## 1. 文献库解析

| 格式 | 方法 | 置信度 |
|-|-|-|
| BibTeX | 逐 `@` 扫描定位条目起点，括号配平（`{}`/`()`）提取正文——**单行与多行条目同一代码路径**；顶层第一个逗号前为 key；字段解析支持 `{...}` 平衡括号值、`"..."` 引号值、裸 token（数字/宏）、`#` 连接；`@string` 宏先定义后展开；`@comment`/`@preamble` 跳过；未闭合条目记 `bibtex_unclosed_entry` | 高 |
| RIS | `TY`/`ER` 界定记录；标签映射 AU/AF→author（多值以 " and " 连接）、TI/T1/BT→title、JO/JF/T2→journal、PY/Y1/DA→year（取首个 4 位年份）、VL→volume、IS→number、SP/BP+EP→pages（连为 `起-止`）、DO→doi、UR/LK→url、PB→publisher 等 | 高 |
| 纯文本 | 行首 `[n]`/`n.` 编号启发式；DOI/年份正则抽取；题名按句段切分（≥3 段时第 1 段记作者、第 2 段记题名） | 低（`low_structure_format` 警告） |
| CSL-JSON | `json.loads` → 数组 / `{references|items|data|entries}` 取记录列表 / `{key: fields}` 兜底；字段映射 `container-title→journal`、`page→pages`、`DOI→doi`、`publisher-place/event-place→address`、`type→文献类型`（`article-journal→article`、`paper-conference→inproceedings`、`chapter→incollection`、`thesis→phdthesis`…）；`author[]` 取 `family, given` 以 " and " 连接；`issued.date-parts[0][0]→year` | 中（字段映射式，非完整 CSL 处理器） |

自动识别：非注释行含 `@type{` → bibtex；含 `TY  -`/`ER  -` → ris；首字符为 `[`/`{` 且为合法 JSON → json；否则 text。可用 `--refs-format` 强制（含 `json`）。

## 2. 去重归并（可解释判据）

候选条目与**全部**已保留条目逐一比较（关键实现细节：内层循环仅在命中合并时 break，比较本身遍历完所有保留条目——这是对“仅与首个保留条目比较后提前退出”缺陷的回归修复）。

判定优先级（`match_pair`）：

1. 双侧 DOI 均格式合法：
   - 归一化后一致 → 合并，basis=`DOI_EXACT`；
   - 不一致但题名归一化一致 → **不合并**，冲突 `kept_separate_needs_human_review`（若含 arXiv 标识，附“可能为预印本/正式版”提示）；
2. 仅一侧（或零侧）有合法 DOI：不足以自动合并；题名/年份一致时给出人工确认建议；
3. 双侧均无合法 DOI 且题名归一化一致：第一作者姓一致 **且** 年份一致 → 合并，basis=`TITLE_AUTHOR_YEAR`；年份或作者不一致/缺失 → 不合并，给出具体理由。

归一化：DOI 去 `doi:`/`https://doi.org/` 前缀、去尾部句点、小写；题名 NFKD 去变音符、去非字母数字（保留 CJK）后小写。

字段并集（`union_fields`，全部记录于 `field_policy`）：保留条目缺字段 → 补自被并条目；作者列表取更长者（原值备份在 `author_original`）。`merged_from` 记录被并 key 供溯源。

设计取舍：宁可漏合并（转人工确认）不可误合并——误合并会破坏“对得上”，漏合并仍保持两条且提示。

## 3. 编号连锁更新与双向一致

- 参考文献节识别：先匹配标题行（Markdown `#`/加粗/裸标题 `参考文献`|`References`|`Bibliography`），命中后只剥离“该标题到下一同级或更高标题之间”的旧文献区，其后附录/图注等内容原样保留并继续按文档序编号（不盲删文末）；否则从文末向前识别连续编号块（`[n]` 或 `n.`/`n、`，≥2 条），但必须块内至少两条且过半行具备内容级书目证据（DOI / `[J]`/`[M]` 等类型标识 / 来源或作者+年份 / 分句作者·题名结构）才判为已有文献节，仅连续纯数字的普通结论/配料/程序清单绝不剥离——避免把原稿文献表当作正文引用重编号、避免输出出现两份列表，也避免误删正文；`plain_list` 情形记 warning，识别方式记入 `main_result.existing_reference_section`。
- 标记识别：`\[(\d+([,，;；]\d+|[-–—~～]\d+)*)\]`，排除后随 `(` 的 Markdown 链接；仅在参考文献节之前的正文处理。
- 旧编号 → 保留条目下标：被合并条目映射到其保留条目（修复：原实现漏掉该映射导致指向被并条目的标记被误判 dangling）。
- 新编号：按正文首次引用出现顺序分配（GB/T 7714 顺序编码制）；未引用条目按文献库原序补在列表末尾并标注“（未在正文引用）”。
- 组内渲染：连续 ≥3 个合并为区间（如 `4-6`），否则逗号；dangling 编号保留原值并整体标注，句子零改写。
- 一致性：每个正文有效标记号 ∈ 文献表编号集合；每个文献表条目要么被引用要么明确标注未引用。

## 4. GB/T 7714—2015 顺序编码制渲染

- 作者：中文作者原样；西文按 `姓, 名` 或无逗号启发式——**两词名按“姓 前”（拼音惯例，如 Zhang Wei → ZHANG W），≥3 词按“姓 后”（西文惯例）**；姓全大写+名首字母（无点）；>3 人截断为“前 3 位 + et al./等”。作者字段末段若为/以明确截断标记（`et al`/`et al.`/`et alii`/`etc.`/`others`/`等`/`等人`，大小写不敏感）结尾，按截断处理（保留真实作者 + et al./等），不再把 `others`/`et al` 当作作者姓名；作者恰好姓 Others 的罕见歧义不在此自动判定，保留人工复核边界。
- 条目：`[n] 作者. 题名[类型标识]. 来源, 年, 卷(期): 页码. DOI: xxx.`；类型标识映射 article→[J]、book/inbook→[M]、incollection→[G]、inproceedings/conference→[C]、phdthesis/mastersthesis→[D]、techreport→[R]、electronic→[EB/OL]、其余→[Z]；专著/会议/学位论文等有 `address`（RIS `CY`/CSL `publisher-place`）时渲染为“出版地: 出版者”。
- 页码 `--`/`–`/`—` 统一为 `-`；缺字段如实标注“（卷期页/来源字段缺失）”“（作者字段缺失）”，不虚构。
- **仅渲染通过格式校验（`^10\.\d{4,9}/\S+$`）的 DOI**；非法 DOI 不渲染、记 `invalid_format_not_verifiable`。
- 双向一致性以机器可查字段落盘：`result.json.consistency`（`ok` = 正文有效标记全部在文献表内、未被引用条目必已被标注、且正文无残留悬空（dangling）标记），`metrics.consistency_ok` 同步；S8d/S12 回归覆盖。

## 5. DOI 核验（离线优先）

- 默认 `off`：每条记 `not_attempted`（含原因说明），不冒充已核验。
- `online`：逐 DOI 调 `https://doi.org/api/handles/{doi}`（UA 标识、8 秒超时、≤50 条）；结果 `verified`/`not_found`/`http_error`/`network_error`/`uncertain` 逐条如实记录。上限截断如实注明。

## 6. 确定性与可复现

无随机源；输出文件均为 UTF-8（LF）；同输入同输出（result.json 仅 `generated_at` 时间戳不同，selfcheck S9 验证）。

## 7. 与基础 Agent/既有工具的差异（创新边界主张）

- 基础 Agent 逐条人工核对编号时常见错位/漏合并；本管线把“合并判据 + 连锁改号 + 双向一致校验”固化为确定性代码，全部决策留痕（basis/field_policy/old→new 映射）。
- 通用文献管理工具（Zotero 等）去重多为界面操作且判据不外显；本管线判据、例外（同名不同 DOI 不合并）与降级路径全部写进 result.json，可直接复核。
- 未主张：语义级论断匹配、全格式支持（见 USAGE.md 限制）。
