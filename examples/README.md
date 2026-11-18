# examples — 最小调用示例（本目录全部内容为**示例**，非官方正式案例、非预制答案）

## 输入（示例，位于 `mini/`）

- `mini/ms_mini.md`：2 个引用标记的示例稿件；
- `mini/refs_mini.bib`：3 条示例文献，其中 `demoA` 与 `demoAdup` 为 DOI 相同的重复条目（题名/期刊写法、作者人数有差异）。

## 调用命令

```bash
python scripts/citation_pipeline.py \
  --manuscript examples/mini/ms_mini.md \
  --refs examples/mini/refs_mini.bib \
  --outdir out_mini
```

## 示意输出（**示例**，由上述示例输入实际运行后摘录；正式案例结果以运行真实输入为准）

`out_mini/result.json` 摘录：

```json
{
  "case_id": null,
  "status": "completed",
  "metrics": {"entries_parsed": 3, "entries_after_merge": 2, "merges": 1,
               "citation_groups": 2, "markers_updated": 2, "dangling_groups": 0,
              "duplicate_conflicts_unmerged": 0, "invalid_doi": 0,
              "uncited_entries": 0, "consistency_ok": true, "doi_online_verification": "off"},
  "output_contract": {"status": "not_provided",
                       "note": "未提供 --case / case.json 中无 output_contract；不伪造合同镜像"}
}
```

`out_mini/manuscript.updated.md`（示意，**示例**）：

```markdown
<!-- 示例输入（自建最小样例，非官方正式案例）：用于演示 citation_pipeline.py 的最小调用 -->
## 引言
本文方法的有效性在实验[1]中得到验证，并与对比工作[2]一致。

## 参考文献
[1] LIN X, GU Y, SHI G. Demo study of citation dedup[J]. J Example, 2023, 7: 45-52. DOI: 10.1000/demo-1.
[2] HAN M. A different work entirely[J]. J Other, 2022, 3: 10-16. DOI: 10.1000/demo-2.

<!-- 引用管理标注（weekly-skill citation_pipeline v2.2.0 自动生成；正文论断未作任何改写，仅更新引用编号与文献表；逐条依据见同目录 result.json）
- 已合并重复条目：demoAdup 并入 demoA（依据 DOI_EXACT：归一化 DOI 一致：10.1000/demo-1）
-->
```

合并依据与字段策略（`result.json → changes`，示意）：

```json
{"action": "merge", "kept": "demoA", "removed": "demoAdup", "basis": "DOI_EXACT",
 "basis_detail": "归一化 DOI 一致：10.1000/demo-1",
 "field_policy": {"author_original": "Lin Xiao and Gu Yuan",
                   "author": "取更长作者列表 demoAdup（2→3 人）"}}
```

## 说明

- 本示例演示：DOI 相同的跨库重复自动合并（含作者列表并集）、编号连锁更新、GB/T 7714—2015 渲染、内嵌文献表与自动标注块。
- 更多场景（反例不误合并、非法 DOI、dangling、BOM/GBK、RIS、CSL-JSON、无标题原稿文献列表剥离重建、双向一致性块、在线核验）由 `scripts/selfcheck.py`（23 项）与方法说明 docs/METHODS.md 覆盖。
