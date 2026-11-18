# USAGE — weekly-skill 使用说明（v2.2.0）

## 依赖与安装

- Python **3.8+**（开发验证环境：Python 3.13.5，Windows）；仅标准库（argparse/hashlib/json/os/re/sys/unicodedata/datetime/urllib），**无需 pip 安装任何包**。
- 脚本位置（相对本 Skill 根目录）：`scripts/citation_pipeline.py`（主管线）、`scripts/selfcheck.py`（不变量自检）。
- 安装方式：整包复制到 `/skills/weekly-skill`（或任意目录，目录名需与 SKILL.md frontmatter `name` 一致）。

## 完整调用步骤

1. 准备输入：稿件 `manuscript.md`（含 `[1]`/`[2,3]`/`[4-6]` 式标记；文末可自带参考文献节——有/无标题均可，会被识别并重建）；文献库 `refs.bib|ris|json|txt`（自动识别格式）；可选 `case.json`（含 `case_id`、`inputs`、`output_contract`）。
2. 运行：

   ```bash
   python scripts/citation_pipeline.py --manuscript manuscript.md --refs refs.bib \
        [--case case.json] --outdir out
   # 或仅用 case 提供输入：
   python scripts/citation_pipeline.py --case case.json --outdir out
   ```

3. 查看 `out/result.json` 的 `status` / `consistency.ok` / `warnings` / `uncertainty` / `changes`；需要人工处理的项目集中在 `main_result.duplicate_conflicts_unmerged`、`main_result.dangling_citations`、`main_result.uncited_entries`。
4. 成品：`out/manuscript.updated.md`（可编辑改稿+内嵌文献表+自动标注块）、`out/references.gbt7714.md`（同步文献表）。

## 输入输出解释

- 输入编码自动识别（utf-8-sig → utf-8 → gb18030），实际编码记录在 `result.json → input.encoding_notes`。
- `result.json` 顶层：`case_id`、`status`（completed / completed-with-warnings / failed）、`main_result`、`sources`（逐条溯源：来源文件+行号+字段+DOI 核验状态）、`uncertainty`、`changes`（合并/改号/渲染/写文件逐条记录）、`consistency`（正文—文献表双向一致性：`ok`、`body_valid_numbers`、`list_numbers`、`dangling_numbers`、`uncited_numbers`）、`warnings`、`output_contract`（原样镜像）与 `output_contract_resolution`（逐字段解析；未识别字段置 null，不伪造）。
- 退出码：0=完成（含带警告完成）；2=输入缺失等失败（仍写 result.json）。

## 关键方法摘要

- 去重两级判据（详见 docs/METHODS.md）：`DOI_EXACT`（归一化 DOI 一致）＞`TITLE_AUTHOR_YEAR`（题名归一化+第一作者姓+年份一致，且双侧无合法 DOI）；同名不同 DOI/年份**不合并**，转 `kept_separate_needs_human_review`。
- 编号：按正文首次引用顺序（顺序编码制），未引用条目按原序补后并标注；被合并条目的旧标记改指保留条目；dangling 标记保留原号并标注，句子零改写。

## 适用场景

学术稿件（中文/英文混合可）投稿前引用整理：去重归并、编号连锁更新、GB/T 7714—2015 顺序编码制文献表、DOI 校验/核验、正文—文献表一致性检查。文献库来源可为 BibTeX、RIS、CSL-JSON（Zotero/Crossref 导出常见）或纯文本编号列表。

## 限制（诚实声明）

- 不支持：著者-出版年制、脚注制、EndNote XML、CNKI 专有导出、PDF 解析、GB/T 7714—2025；`--style` 仅 `gbt7714-2015-numeric`。
- CSL-JSON 为字段映射式解析（常见字段见 METHODS.md §2.4），非完整 CSL 处理器：未映射字段如实忽略，不伪造。
- 无标题末尾编号列表的识别为启发式（≥2 条，且块内过半行具备内容级书目证据：DOI / [J][M] 等类型标识 / 来源或作者+年份 / 分句作者·题名结构）；仅连续纯数字的普通结论/配料/程序清单不会被剥离；命中即剥离重建并给 warning，方式记入 `main_result.existing_reference_section`。
- 带 `参考文献` 标题的旧文献区只剥离“标题到下一同级或更高标题之间”，其后附录/图注等内容原样保留并继续编号。
- 不做正文论断与文献主题的语义匹配（需人工/LLM 复核，SKILL.md §4 步骤 4）。
- 纯文本文献库为启发式解析（`low_structure_format` 警告），字段抽取不保证完整。
- 拼音双词名作者按“姓在前”启发式（西文三词以上按“姓在后”），见 METHODS.md §4；末段为/以明确截断标记（`et al`/`et al.`/`etc.`/`others`/`等`/`等人`）结尾时不再当作作者姓名渲染。
- 已知未修（语义/策略级，本版不做硬规则）：合并会议版+预印本时正式会场可能被预印本来源取代（venue 优先级未做语义判断，转人工复核）；已渲染产物二次运行不保证幂等（本管线按“单次处理原始稿件”假设运行）；行内 `[1] xxx / [2] yyy` 式编号枚举会被当作引用重编号。以上均以 `uncertainty`/本限制如实声明，不夸大自动语义判断能力。

## 失败处理

见 SKILL.md §7 表：缺输入→exit 2 + failed；case 损坏/BOM→降级警告继续；非法 DOI→不渲染不装核验；网络不可达→如实 network_error。

## 自查方法

```bash
python scripts/selfcheck.py   # 23 项不变量（S1–S9 历史缺陷回归 + S10–S14 本轮新增），退出码 0/1
```

## 维护信息

- 版本 v2.2.0。相对 v2.1.0 的修复（正确性/可核验性，无编排扩展）：① `result.json.main_result.reference_list[].number/keys/cited` 与渲染文本及 `sources` 逐条对齐（首次引用顺序≠文献库原序时不再错位）；② 带 `参考文献` 标题时仅剥离标题到下一同级/更高标题之间的旧文献区，其后附录/图注原样保留；③ 无标题末尾编号列表改为内容级书目证据判定，普通结论/配料/程序清单不再误删，且放宽“必须从 1 起且连续”的假设；④ `consistency.ok` 在正文仍有悬空（dangling）标记时为 False，区分未引用条目与悬空标记；⑤ 末段 `et al`/`等` 截断标记不再被当作作者姓名渲染。
- 版本 v2.1.0（相对 v2.0.0 的变更：CSL-JSON 文献库；无标题原稿文献列表的识别/重建；正文—文献表一致性块 consistency；[M]/[C]/[G]/[R]/[D] 按“出版地: 出版者”渲染；selfcheck 18→23 项）。本包为比赛提交物，脚本为单一文件、无外部资源依赖，便于审计与复用。
- 已知未实现项与未测项以 result.json `uncertainty` 与包内文档声明为准，不冒充已支持。
