#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""selfcheck.py v2.2.0 — citation_pipeline 不变量自检（示例夹具全部为自建样例，非官方案例）。

覆盖：
  S1  BibTeX 单行完整 @article 条目解析（历史回归：单行条目解析失败/丢条目）
  S2  去重次序回归（历史回归：仅与首个保留条目比较后提前退出，≥3 条时漏合并）
  S3  题名+第一作者姓+年份一致且双侧无 DOI → 合并（判据可解释）
  S4  题名一致但 DOI/年份不同 → 不合并 + 冲突标记（不误合并）
  S5  非法 DOI 不渲染为 DOI、记不可核验（不伪装可核验）
  S6  UTF-8 BOM case.json 可解析，合同字段全镜像（历史回归：BOM 崩溃/镜像不全）
  S7  无 case 运行 → output_contract 诚实记 not_provided
  S8  dangling 标记原样保留、不删句；双向一致；编号连续
  S9  同输入重复运行结果稳定（除 generated_at 外一致）
  S10 原稿无标题末尾编号文献列表被剥离重建（回归：旧列表曾被当正文引用重写并留下重复列表）
  S11 CSL-JSON / JSON 文献库可解析（本轮新增能力；含 book 出版地: 出版者）
  S12 result.json 含正文—文献表双向一致性块且闭合
  S13 完全缺 --manuscript → exit 2 且写 failed result.json（诚实失败合同）
  S14 --refs-format json 强制指定可用

用法：python selfcheck.py   （退出码 0=全部通过，1=有失败）
"""
import json
import os
import re
import shutil
import sys
import tempfile

sys.dont_write_bytecode = True  # 不在 Skill 包内遗留 __pycache__
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import citation_pipeline as cp  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail and not ok else ""))


def run_pipe(tmp, ms, refs, extra=None, case=None):
    out = os.path.join(tmp, "out_" + re.sub(r"\W+", "", ms + refs) + (case or ""))
    argv = ["--manuscript", os.path.join(tmp, ms), "--refs", os.path.join(tmp, refs),
            "--outdir", out] + (extra or [])
    if case:
        argv += ["--case", os.path.join(tmp, case)]
    code = cp.run(argv)
    with open(os.path.join(out, "result.json"), encoding="utf-8") as f:
        return code, json.load(f), out


def main():
    tmp = tempfile.mkdtemp(prefix="citself_")
    try:
        # ---- 夹具（自建示例，非官方案例） ----
        with open(os.path.join(tmp, "ms.md"), "w", encoding="utf-8") as f:
            f.write("## 引言\n论断甲[1]与论断乙[2]一致；综述见[4-6]与[7]。\n\n"
                    "## 参考文献\n（占位）\n")
        with open(os.path.join(tmp, "ms_clean.md"), "w", encoding="utf-8") as f:
            f.write("## 引言\n论断甲[1]与论断乙[2]一致。\n\n## 参考文献\n（占位）\n")
        # S1 单行条目 + 多行条目混排（历史回归：单行条目丢条目）
        with open(os.path.join(tmp, "one.bib"), "w", encoding="utf-8") as f:
            f.write("@article{a, author={Zhang San}, title={Solo line entry}, "
                    "journal={J One}, year={2020}, volume={1}, pages={1--9}, "
                    "doi={10.1000/one}}\n"
                    "@article{b,\n  author={Li Si},\n  title={Multi line entry},\n"
                    "  journal={J Two}, year={2021},\n  doi={10.1000/two}}\n")
        # S2 去重次序回归：前两条 DOI 不同、后两条 DOI 相同 → 必须合并
        with open(os.path.join(tmp, "ord.bib"), "w", encoding="utf-8") as f:
            f.write("@article{a, author={A U}, title={Alpha}, journal={J}, year={2019}, doi={10.1000/a}}\n"
                    "@article{b, author={B V}, title={Beta}, journal={J}, year={2019}, doi={10.1000/b}}\n"
                    "@article{b2, author={B V and C W}, title={Beta}, journal={J}, year={2019}, doi={10.1000/b}}\n")
        # S3 无 DOI 同文判据；S4 同题名不同 DOI/年份
        with open(os.path.join(tmp, "noDOI.bib"), "w", encoding="utf-8") as f:
            f.write("@article{n1, author={Wang Wu}, title={Same title here}, journal={J}, year={2020}}\n"
                    "@article{n2, author={Wang Wu and Zhao Liu}, title={Same title here.}, journal={J.}, year={2020}}\n"
                    "@article{x1, author={Sun Qi}, title={Same title here}, journal={J}, year={2018}}\n"
                    "@article{x2, author={Zhou Ba}, title={Same title here}, journal={J2}, year={2020}, doi={10.1/x}}\n")
        # S5 非法 DOI + dangling 场景
        with open(os.path.join(tmp, "bad.bib"), "w", encoding="utf-8") as f:
            f.write("@article{g1, author={He Jiu}, title={Good one}, journal={J}, year={2020}, doi={10.1000/g}}\n"
                    "@article{bad1, author={Wu Shi}, title={Bad doi entry}, journal={V}, year={2021}, doi={not-a-doi:broken}}\n"
                    "@article{u1, author={Zheng Yi}, title={Never cited entry}, journal={J}, year={2022}, doi={10.1000/u}}\n")
        # S6 BOM case.json
        with open(os.path.join(tmp, "case_bom.json"), "wb") as f:
            f.write(b"\xef\xbb\xbf" + json.dumps({
                "case_id": "SELF-BOM-001",
                "inputs": {"manuscript": "ms.md", "refs": "one.bib"},
                "output_contract": {"manuscript_updated": "path", "references_list": "path",
                                    "result_json_required_fields": ["case_id", "status", "main_result",
                                                                    "sources", "uncertainty", "changes"],
                                    "style": "GB/T 7714—2015 顺序编码制",
                                    "custom_unknown_field": "x"},
            }, ensure_ascii=False).encode("utf-8"))

        # ---- S1 单行条目解析 ----
        code, r, _ = run_pipe(tmp, "ms.md", "one.bib")
        ent = {s["key"] for s in r["sources"]}
        check("S1a 单行/多行条目均解析（a、b 都在）", code == 0 and ent == {"a", "b"}, f"got {ent}")
        f1 = {s["key"]: s["fields"] for s in r["sources"]}
        check("S1b 单行条目字段完整（volume/pages/doi 不丢）",
              f1["a"].get("volume") == "1" and f1["a"].get("pages") == "1--9"
              and f1["a"].get("doi") == "10.1000/one", str(f1.get("a")))

        # ---- S2 去重次序回归 ----
        code, r, _ = run_pipe(tmp, "ms.md", "ord.bib")
        m = r["main_result"]
        check("S2a ≥3 条且前两条 DOI 不同、后两条相同 → 恰 1 次合并（3→2）",
              m["entries_parsed"] == 3 and m["entries_after_merge"] == 2 and len(m["merges"]) == 1,
              json.dumps(r["metrics"], ensure_ascii=False))
        check("S2b 合并依据可解释（DOI_EXACT 且记录于 changes）",
              m["merges"] and m["merges"][0]["basis"] == "DOI_EXACT"
              and any(c.get("action") == "merge" for c in r["changes"]))

        # ---- S3/S4 无 DOI 判据 / 不误合并 ----
        code, r, _ = run_pipe(tmp, "ms.md", "noDOI.bib")
        m = r["main_result"]
        keys_merged = {mm["kept"] for mm in m["merges"]}
        check("S3 无 DOI 同文同作者同年 → n1/n2 合并（TITLE_AUTHOR_YEAR）",
              "n1" in keys_merged and any(mm["basis"] == "TITLE_AUTHOR_YEAR" for mm in m["merges"]),
              json.dumps(m["merges"], ensure_ascii=False))
        check("S4 同题名不同年份/DOI → 不合并且给冲突标记",
              m["entries_after_merge"] == 3
              and any("x1" in c["keys"] for c in m["duplicate_conflicts_unmerged"]),
              json.dumps(m["duplicate_conflicts_unmerged"], ensure_ascii=False))

        # ---- S5 非法 DOI 不渲染 + S8 dangling 保留 ----
        code, r, out = run_pipe(tmp, "ms.md", "bad.bib")
        refs_txt = open(os.path.join(out, "references.gbt7714.md"), encoding="utf-8").read()
        ms_txt = open(os.path.join(out, "manuscript.updated.md"), encoding="utf-8").read()
        check("S5a 非法 DOI 不渲染为 DOI 字样", "not-a-doi" not in refs_txt and "DOI: not" not in refs_txt)
        bad_src = [s for s in r["sources"] if s["key"] == "bad1"]
        check("S5b 非法 DOI 记为不可核验（不声称已核验）",
              bad_src and bad_src[0]["doi_check"]["verification"] == "invalid_format_not_verifiable")
        check("S8a dangling 标记原样保留且不删句",
              "综述见[4-6]与[7]" in ms_txt and "论断甲[1]" in ms_txt, ms_txt[:200])
        check("S8b 每条 warning 均入 uncertainty",
              any(w["type"] == "dangling_citation" for w in r["uncertainty"])
              and any(w["type"] == "invalid_doi_format" for w in r["uncertainty"]))
        nums = [e["number"] for e in r["main_result"]["reference_list"]]
        check("S8c 文献表编号连续 1..N", sorted(nums) == list(range(1, len(nums) + 1)), str(nums))
        # 双向一致：正文渲染标记中的有效编号都在列表内
        valid_in_text = set()
        for g in r["main_result"]["citation_groups"]:
            valid_in_text |= set(g["new_numbers"])
        check("S8d 正文有效标记均有列表条目（双向一致）", valid_in_text <= set(nums),
              f"text={sorted(valid_in_text)} list={nums}")
        uncited = [e["number"] for e in r["main_result"]["reference_list"] if not e["cited"]]
        check("S8e 未引用条目被明确标注", all("未在正文引用" in e["gbt7714"] for e in
                                              r["main_result"]["reference_list"] if not e["cited"])
              and uncited, str(uncited))

        # ---- S6 BOM case + 合同镜像 ----
        code, r, _ = run_pipe(tmp, "ms.md", "one.bib", case="case_bom.json")
        contract_keys = set(r["output_contract"].keys())
        check("S6a BOM case.json 不崩溃（exit 0）且 case_id 保留", code == 0 and r["case_id"] == "SELF-BOM-001")
        check("S6b output_contract 全部字段名出现在 result.json",
              contract_keys == {"manuscript_updated", "references_list", "result_json_required_fields",
                                "style", "custom_unknown_field"}
              and set(r["output_contract_resolution"].keys()) == contract_keys
              and r["output_contract_resolution"]["custom_unknown_field"] is None,
              json.dumps(r["output_contract_resolution"], ensure_ascii=False))
        req = r["result_json_required_fields_check"]
        check("S6c result.json 顶层必备字段齐备", req and all(req.values()), str(req))

        # ---- S7 无 case → 诚实 not_provided ----
        code, r, _ = run_pipe(tmp, "ms.md", "one.bib")
        check("S7 无 case 时合同诚实记 not_provided（不伪造）",
              r["output_contract"].get("status") == "not_provided"
              and r["case_id"] is None)

        # ---- S10 原稿已有无标题文献列表：剥离重建，不留重复 ----
        with open(os.path.join(tmp, "ms_plainlist.md"), "w", encoding="utf-8") as f:
            f.write("## 引言\n论断甲[1]。\n\n1. Zhang San. Alpha. J, 2020.\n2. Wang Wu. Beta. J, 2019.\n")
        code, r, out = run_pipe(tmp, "ms_plainlist.md", "one.bib")
        up = open(os.path.join(out, "manuscript.updated.md"), encoding="utf-8").read()
        body = up.split("## 参考文献")[0]
        check("S10 无标题末尾编号列表被剥离重建（正文不留旧列表、无重复列表、给 warning）",
              code == 0 and "1. Zhang San. Alpha" not in body and up.count("## 参考文献") == 1
              and any(w["type"] == "existing_reference_section_rebuilt" for w in r["warnings"]),
              up[:300])

        # ---- S11 CSL-JSON 文献库 ----
        with open(os.path.join(tmp, "refs.json"), "w", encoding="utf-8") as f:
            json.dump([{"id": "c1", "type": "article-journal", "title": "Nitrogen reduction",
                        "author": [{"family": "Zhang", "given": "Wei"}], "container-title": "J. Catal.",
                        "issued": {"date-parts": [[2020]]}, "volume": "381", "page": "23-31",
                        "DOI": "10.1016/j.jcat.2020.01.001"},
                       {"id": "c2", "type": "book", "title": "Handbook",
                        "author": [{"family": "Smith", "given": "John"}], "publisher": "Springer",
                        "publisher-place": "Berlin", "issued": {"date-parts": [[2018]]}}], f)
        code, r, out = run_pipe(tmp, "ms_clean.md", "refs.json")
        refs_txt = open(os.path.join(out, "references.gbt7714.md"), encoding="utf-8").read()
        check("S11 CSL-JSON 解析（2 条，含作者/年份/期刊/DOI 与 book 出版地: 出版者）",
              code == 0 and r["input"]["refs_format_detected"] == "json"
              and r["main_result"]["entries_parsed"] == 2
              and "10.1016/j.jcat.2020.01.001" in refs_txt and "Berlin: Springer" in refs_txt,
              refs_txt)

        # ---- S12 双向一致性块 ----
        check("S12 result.json 含双向一致性块且 ok=true",
              (r.get("consistency") or {}).get("ok") is True
              and (r.get("metrics") or {}).get("consistency_ok") is True)

        # ---- S14 强制 --refs-format json ----
        code, r2, _ = run_pipe(tmp, "ms.md", "refs.json", extra=["--refs-format", "json"])
        check("S14 --refs-format json 强制指定可用",
              code == 0 and r2["main_result"]["entries_parsed"] == 2)

        # ---- S13 完全缺 --manuscript → exit 2 + failed result.json ----
        out_noms = os.path.join(tmp, "out_noms")
        code = cp.run(["--refs", os.path.join(tmp, "refs.json"), "--outdir", out_noms])
        res_noms = os.path.join(out_noms, "result.json")
        st = json.load(open(res_noms, encoding="utf-8"))["status"] if os.path.isfile(res_noms) else None
        check("S13 完全缺 --manuscript → exit 2 且写 failed result.json",
              code == 2 and st == "failed", f"code={code} status={st}")
        # ---- S9 重复运行稳定性 ----
        _, r1, o1 = run_pipe(tmp, "ms.md", "ord.bib")
        _, r2, o2 = run_pipe(tmp, "ms.md", "ord.bib", case=None)
        r1.pop("generated_at", None), r2.pop("generated_at", None)
        check("S9 同输入重复运行结果稳定（除时间戳外逐字一致）", r1 == r2)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    fails = [x for x in RESULTS if not x[1]]
    print(f"\nselfcheck: {len(RESULTS) - len(fails)}/{len(RESULTS)} passed")
    return 1 if fails else 0


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    sys.exit(main())
