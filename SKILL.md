---
name: weekly-skill
description: 参考文献与引用管理确定性管线：给定一份稿件和一份文献库（BibTeX/RIS/CSL-JSON/纯文本编号列表），自动完成文献去重归并（DOI 精确合并 + 题名/第一作者/年份保守判据，依据可解释）、正文引用编号连锁更新（含被合并条目改指保留条目、dangling 标记原样保留）、原稿已有参考文献节的识别与重建（带标题时仅剥离该标题到下一同级/更高标题之间的旧文献区、其后附录原样保留；无标题的末尾编号列表按内容级书目证据识别，避免重复列表与误删）、GB/T 7714—2015 顺序编码制文献表渲染（含 `et al`/`等` 截断标记识别）、正文—文献表双向一致性检查（区分未引用条目与悬空标记，结果写入 consistency 字段）、DOI 格式校验与可选在线核验（默认离线、诚实降级），输出可编辑改稿、同步文献表与镜像 output_contract 的 result.json。适用于学术稿件引用整理、投稿前文献核查；不适用于著者-出版年制、脚注制、EndNote XML 与 PDF 解析。
compatibility: Python 3.8+，仅标准库，无需安装依赖；离线可运行（在线 DOI 核验可选）；输入容忍 UTF-8/UTF-8 BOM/GB18030 编码。
---

# weekly-skill — 参考文献与引用管理（编号同步 + 去重归并 + 来源核验）

## 1. 用途与聚焦

本 Skill 解决学术写作中“参考文献与引用管理”的一个明确闭环（题面允许聚焦单一问题）：

- **编得顺**：插入/删除/合并条目后，正文编号与文末列表连锁更新，编号连续、双向一致；
- **收得净**：同一文献以 DOI 相同（跨库导出、题名/作者排布差异）或“题名归一化一致 + 第一作者姓一致 + 年份一致（双侧无合法 DOI）”重复出现时合并为一条，给出可解释合并依据；同名不同 DOI/年份的**绝不误合并**，转人工确认；
- **对得上（元数据层）**：逐条 DOI 格式校验；非法 DOI 不渲染、不声称可核验；可选在线核验（doi.org handle API），未开启即如实记 `not_attempted`；
- 每一步改动（合并、改号、渲染、写文件）逐条写入 result.json 的 `changes`，可回溯。

**不做**（诚实边界，见 §7）：论断级“正文句子 ↔ 文献主题”语义匹配（留给 Agent 人工复核步骤）、著者-出版年制/脚注制、EndNote XML/CNKI 专有格式、PDF 解析、GB/T 7714—2025。

## 2. 适用条件

- 输入：一份稿件（Markdown/纯文本，含 `[1]`、`[2,3]`、`[4-6]` 式顺序编码标记，文末可自带参考文献节）+ 一份文献库（BibTeX / RIS / CSL-JSON / 纯文本编号列表，自动识别；可用 `--refs-format` 强制）。
- 环境：Python 3.8+，仅标准库。默认离线运行；`--verify-doi online` 需要出网（每 DOI 上限 8 秒，超过 50 条截断并如实注明）。
- 编码：UTF-8 / UTF-8 BOM / GB18030 自动识别（result.json 的 `input.encoding_notes` 记录实际编码）。

## 3. 调用方式

### 3.1 标准路径（评测运行时合同：/input → /app/output）

```bash
# 输入：/input/case.json 与 /input/task.md（实际文件以平台提供为准，读取真实文件而非假设）
python /skills/weekly-skill/scripts/citation_pipeline.py \
  --case /input/case.json \
  --outdir /app/output
```

- `--case` 会读取 `case_id`、`inputs.manuscript`、`inputs.refs`（相对路径按 case.json 所在目录解析）与 `output_contract`。
- 若 case.json 未给出输入路径（或损坏），用显式参数兜底：

```bash
python /skills/weekly-skill/scripts/citation_pipeline.py \
  --manuscript /input/manuscript.md --refs /input/refs.bib \
  [--case /input/case.json] --outdir /app/output
```

### 3.2 参数

| 参数 | 取值 | 说明 |
|-|-|-|
| `--manuscript` | 路径 | 稿件文件（Markdown/纯文本） |
| `--refs` | 路径 | 文献库（bibtex/ris/json/text 自动识别） |
| `--case` | 路径 | case.json（case_id + output_contract 镜像） |
| `--outdir` | 目录 | 输出目录（默认 `./out`） |
| `--refs-format` | auto/bibtex/ris/json/text | 强制指定文献库格式（默认 auto：按内容自动识别） |
| `--style` | gbt7714-2015-numeric | 当前版本仅实现 GB/T 7714—2015 顺序编码制，其余如实报错不伪造 |
| `--verify-doi` | off/online | DOI 在线核验，默认 off（评测环境联网情况未知，离线诚实降级为 not_attempted） |

### 3.3 输出（写入 `--outdir`）

| 文件 | 内容 |
|-|-|
| `manuscript.updated.md` | 可编辑改稿：正文标记按新编号重渲染（dangling 原样保留）；在原“参考文献”标题处重建文献表，标题后的附录/图注等内容原样保留并继续按文档序编号；末尾附自动标注注释块（合并/冲突/异常 DOI/未引用/dangling），**正文论断零改写** |
| `references.gbt7714.md` | 同步文献表（GB/T 7714—2015 顺序编码制；未引用条目标注“（未在正文引用）”） |
| `result.json` | 结构化结果：`case_id`、`status`、`main_result`、`sources`、`uncertainty`、`changes`、`consistency`（正文—文献表双向一致性检查：`body_valid_numbers`/`list_numbers`/`dangling_numbers`/`uncited_numbers`/`ok`）、`warnings`，并**原样镜像 output_contract 全部字段**（`output_contract` + 逐字段解析 `output_contract_resolution`）；无 case 时如实记 `not_provided` |

### 3.4 退出码与状态

- `0` + `status=completed`：全部正常；
- `0` + `status=completed-with-warnings`：完成但有需注意项（dangling 标记、疑似重复未合并、非法 DOI、未引用条目、启发式解析降级等），全部列入 `warnings` 与 `uncertainty`；
- `2` + `status=failed`：输入缺失等无法运行的情形（仍会写出 result.json，不抛崩溃栈）。

## 4. Agent 执行流程（评测时按此走）

1. 读真实输入 `/input/case.json`、`/input/task.md`（以及其中指明的材料文件；BOM/GBK 均容忍）。
2. 按 §3.1 运行管线（优先 `--case`；路径缺失用显式参数兜底）。
3. 读 `result.json`：检查 `status`、`consistency.ok`、`warnings`、`main_result.duplicate_conflicts_unmerged`、`main_result.dangling_citations`。
4. **人工/LLM 复核步（不虚构）**：对冲突条目对（同名不同 DOI/年份、疑似预印本/正式版）与 dangling 标记逐条判断，将结论以追加字段（如 `human_review`）写入 result.json 或另存复核文件；判断不确定的保持“待人工确认”，不改写正文论断、不虚构核验结果。
5. 确认 `/app/output/` 内 `manuscript.updated.md`、`references.gbt7714.md`、`result.json` 齐备且 result.json 保留原 `case_id` 与全部 `output_contract` 字段。
6. 需要论断级一致性检查时：以 `result.json.sources` 的逐条溯源（文件+行号+字段）为线索人工比对，不冒充自动语义核验。

## 5. 方法要点（详见 docs/METHODS.md）

- **解析**：BibTeX 逐 `@` 扫描 + 括号配平（单行/多行条目一致处理，`@string` 宏展开）；RIS 按 `TY/ER` 记录映射字段（AU/AF/TI/JO/PY/VL/IS/SP/EP/DO/UR…）；CSL-JSON 数组 / `{references|items|data: [...]}` / `{key: fields}` 映射（`container-title→journal`、`issued.date-parts→year`、`author[].family/given→作者`）；纯文本编号列表启发式抽取并声明 `low_structure_format` 低置信。
- **去重**：候选与**全部**保留条目逐一比较（无提前退出）。合并判据两级：`DOI_EXACT`（归一化后 DOI 一致）＞`TITLE_AUTHOR_YEAR`（题名归一化一致+第一作者姓一致+年份一致，且双侧均无合法 DOI）。字段并集策略：缺失字段补自对方、作者取更长列表，全部记录于 `field_policy`。
- **改号**：顺序编码制按正文**首次引用顺序**编号（含参考文献标题之后的附录/图注等保留区）；未引用条目按原序补在列表末尾并标注；被合并条目的旧标记改指保留条目；dangling 标记（含范围展开后超界的）保留原编号并标注，不删句、不改写。
- **渲染**：GB/T 7714—2015：作者“姓大写+名首字母”，>3 人截断“前 3 + et al./等”，末段明确截断标记（`et al`/`等` 等）不再当作作者姓名渲染；文献类型标识 [J]/[M]/[C]/[D]/[R]/[EB/OL]；专著/会议/学位论文等按“出版地: 出版者”渲染（有 `address`/`publisher-place` 时）；仅渲染格式合法的 DOI（`^10\.\d{4,9}/\S+$`）。

## 6. 最小调用示例

见 [examples/README.md](examples/README.md)（输入、命令与**示意输出**均标注为示例，非正式案例结果）。

## 7. 限制与失败处理

| 情形 | 处置 |
|-|-|
| 文献库 0 条 / 格式不可识别 | 记 warning，按 text 启发式兜底或 `no_entries_parsed`，不伪造条目；JSON 解析失败记 `json_unparseable` |
| case.json 缺失/损坏/BOM | 不崩溃：warning + `case_unparseable`，合同镜像记 `not_provided`，继续处理显式输入 |
| 稿件或文献库文件缺失 / 未提供 `--manuscript` | exit 2 + `status=failed`，**仍写 result.json**（不抛崩溃栈） |
| 非法 DOI | 不渲染、记 `invalid_format_not_verifiable`，绝不声称已核验 |
| 在线核验不可达/超时 | 逐条如实记 `network_error`/`http_error`；默认 off 时记 `not_attempted` |
| 同名不同 DOI/年份 | 保守不合并，`kept_separate_needs_human_review` + 理由（含 arXiv 预印本/正式版提示） |
| 合并会议版+预印本 / 二次运行 / 行内编号枚举 | 已知未修（语义/策略级，本版不做硬规则）：合并时正式会场可能被预印本来源取代；已渲染产物二次运行不保证幂等；行内 `[1] xxx` 式编号枚举会被当引用重编号。如实声明，转人工复核，不夸大自动语义判断 |
| 原稿末尾已有参考文献节（含无标题的编号列表） | 带标题时只剥离该标题到下一同级/更高标题之间的旧文献区，其后附录/图注原样保留并继续编号；无标题末尾编号列表按内容级书目证据识别（仅连续纯数字的普通结论/配料/程序清单绝不剥离）；先剥离再按新编号重建，避免把已有文献表当作正文引用重编号或留下重复列表；`plain_list` 情形记 `existing_reference_section_rebuilt` warning；方式记入 `main_result.existing_reference_section` |
| 著者-出版年制/脚注制/EndNote XML/CNKI 专有导出/PDF | 不支持，`uncertainty.scope` 明示；`--style` 传其他值直接报错 |

## 8. 自查方法

```bash
python /skills/weekly-skill/scripts/selfcheck.py
# 23 项不变量：S1–S9 历史回归（单行条目、去重次序、无 DOI 判据、不误合并、非法 DOI、BOM case、
# 无 case 诚实声明、dangling 保留与双向一致、重复运行稳定）+ S10 无标题文献列表剥离重建、
# S11 CSL-JSON 解析、S12 一致性块、S13 缺 --manuscript 诚实失败、S14 强制 --refs-format json
```

版本：citation_pipeline.py / selfcheck.py v2.2.0。变更与已知限制见 docs/USAGE.md 与 docs/METHODS.md。
