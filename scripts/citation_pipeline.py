#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""citation_pipeline.py v2.2.0 — 参考文献与引用管理确定性管线。

聚焦问题（题面允许聚焦单一问题）：编号更新与正文—文献表一致性 + 文献去重归并（可解释判据）
+ 来源核验（DOI 格式校验，在线核验默认关闭、诚实降级）。

设计原则：
- 确定性、可复跑：无随机性；除 generated_at 时间戳外，同输入同输出。
- 不虚构：缺字段如实标注，非法 DOI 不渲染为可核验 DOI，在线核验未做即记 not_attempted。
- 不改写正文论断：dangling 引用标记原样保留并标注；仅更新编号与重建文献列表。
- 宽容输入：UTF-8/UTF-8 BOM/GB18030；BibTeX 单行与多行条目、RIS、CSL-JSON/JSON、纯文本编号列表（启发式）。

仅依赖 Python 3.8+ 标准库。默认离线运行。
"""
import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone

VERSION = "2.2.0"
SKILL_NAME = "weekly-skill"

STYLE = "GB/T 7714—2015 顺序编码制"
DOC_TYPE = {
    "article": "J", "book": "M", "inbook": "M", "incollection": "G",
    "inproceedings": "C", "conference": "C", "phdthesis": "D", "mastersthesis": "D",
    "techreport": "R", "patent": "P", "electronic": "EB/OL", "online": "EB/OL",
    "misc": "Z", "unpublished": "Z",
}
FIELD_ORDER = ["author", "title", "journal", "booktitle", "publisher", "institution",
               "school", "address", "year", "volume", "number", "pages", "doi", "url",
               "edition", "issn", "isbn", "language", "note", "keywords"]
CJK_RE = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf]')


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- IO helpers
def sha256_bytes(raw):
    return hashlib.sha256(raw).hexdigest()


def read_text(path):
    """宽容读取：utf-8-sig（BOM）→ utf-8 → gb18030 → utf-8(replace)。返回 (text, encoding)。"""
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8(errors=replace)"


def write_text(path, text):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def sha256_file(path):
    with open(path, "rb") as f:
        return sha256_bytes(f.read())


# ---------------------------------------------------------------- case
def load_case(path, warnings):
    """读 case.json（BOM 容忍）。解析失败不崩溃：记录 warning 返回 None。"""
    try:
        text, enc = read_text(path)
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("case.json 顶层不是对象")
        return data, enc
    except FileNotFoundError:
        warnings.append({"type": "case_file_missing", "detail": str(path)})
    except (ValueError, json.JSONDecodeError) as e:
        warnings.append({"type": "case_unparseable", "detail": f"{path}: {e}"})
    return None, None


def case_inputs(case, case_dir):
    """从 case.inputs 尽力定位稿件与文献库路径；未给返回 None。"""
    if not case:
        return None, None
    inputs = case.get("inputs") or {}

    def pick(*names):
        for n in names:
            v = inputs.get(n)
            if isinstance(v, str) and v.strip():
                p = v if os.path.isabs(v) else os.path.join(case_dir, v)
                return p
        return None

    ms = pick("manuscript", "manuscript_path", "draft", "article")
    refs = pick("refs", "references", "refs_path", "bibliography", "bib")
    return ms, refs


# ---------------------------------------------------------------- BibTeX 解析
def _skip_to_comma(s, i):
    depth = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == "{":
            depth += 1
        elif c == "}":
            if depth == 0:
                return i + 1
            depth -= 1
        elif c == "," and depth == 0:
            return i + 1
        i += 1
    return i


def _read_value(s, i, strings):
    """读一个 BibTeX 值：{..} 平衡括号 / \"..\" / 裸 token / # 连接。"""
    n = len(s)
    parts = []
    while True:
        while i < n and s[i] in " \t\r\n":
            i += 1
        if i >= n:
            break
        if s[i] == "{":
            depth, i, st = 1, i + 1, i + 1
            while i < n:
                if s[i] == "{":
                    depth += 1
                elif s[i] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            parts.append(s[st:i] if i < n else s[st:])
            i += 1
        elif s[i] == '"':
            i += 1
            buf = []
            while i < n and s[i] != '"':
                if s[i] == "{":
                    d, st = 1, i
                    i += 1
                    while i < n and d > 0:
                        if s[i] == "{":
                            d += 1
                        elif s[i] == "}":
                            d -= 1
                            if d == 0:
                                break
                        i += 1
                    buf.append(s[st:i + 1] if i < n else s[st:])
                    i += 1
                else:
                    buf.append(s[i])
                    i += 1
            i += 1
            parts.append("".join(buf))
        else:
            m = re.match(r"[^,}#\s]+", s[i:])
            if not m:
                break
            tok = m.group(0)
            parts.append(tok if tok.isdigit() else strings.get(tok.lower(), tok))
            i += m.end()
        j = i
        while j < n and s[j] in " \t\r\n":
            j += 1
        if j < n and s[j] == "#":
            i = j + 1
            continue
        break
    return " ".join(" ".join(parts).split()), i


def _parse_fields(s, strings):
    fields = {}
    dup = []
    i, n = 0, len(s)
    while i < n:
        while i < n and (s[i].isspace() or s[i] == ","):
            i += 1
        if i >= n:
            break
        m = re.match(r"[A-Za-z][A-Za-z0-9_+.\-]*", s[i:])
        if not m:
            i = _skip_to_comma(s, i)
            continue
        name = m.group(0).lower()
        i += m.end()
        while i < n and s[i].isspace():
            i += 1
        if i >= n or s[i] != "=":
            i = _skip_to_comma(s, i)
            continue
        i += 1
        val, i = _read_value(s, i, strings)
        if val:
            if name in fields:
                dup.append(name)
            else:
                fields[name] = val
        while i < n and s[i].isspace():
            i += 1
        if i < n and s[i] == ",":
            i += 1
    return fields, dup


def parse_bibtex(text, src="refs.bib"):
    """逐 '@' 扫描 + 括号配平；单行/多行条目同样处理；@string 展开宏；@comment/@preamble 跳过。"""
    entries, warnings, strings = [], [], {}
    i, n = 0, len(text)
    while True:
        at = text.find("@", i)
        if at < 0:
            break
        m = re.match(r"@([A-Za-z]+)\s*([\{\(])", text[at:])
        if not m:
            i = at + 1
            continue
        etype = m.group(1).lower()
        opener = m.group(2)
        closer = "}" if opener == "{" else ")"
        body_start = at + m.end()
        depth, j = 1, body_start
        while j < n and depth > 0:
            if text[j] == opener:
                depth += 1
            elif text[j] == closer:
                depth -= 1
            j += 1
        if depth != 0:
            warnings.append({"type": "bibtex_unclosed_entry",
                             "detail": f"@{etype} at offset {at} 未闭合，已跳过"})
            break
        body = text[body_start:j - 1]
        line_no = text.count("\n", 0, at) + 1
        i = j
        if etype == "comment":
            continue
        if etype in ("string", "preamble"):
            if etype == "string":
                mm = re.match(r"\s*([A-Za-z0-9_.:+\-]+)\s*=\s*(.+)$", body, re.S)
                if mm:
                    val, _ = _read_value(mm.group(2), 0, strings)
                    strings[mm.group(1).lower()] = val
            continue
        # key = 顶层第一个逗号之前
        key, rest = body, ""
        d = 0
        for idx, ch in enumerate(body):
            if ch in "{(":
                d += 1
            elif ch in "})":
                d -= 1
            elif ch == "," and d == 0:
                key, rest = body[:idx], body[idx + 1:]
                break
        key = key.strip()
        fields, dup = _parse_fields(rest, strings)
        if dup:
            warnings.append({"type": "bibtex_duplicate_field",
                             "detail": f"条目 {key or '(no-key)'} 字段 {dup} 重复，取首个"})
        if not key:
            key = f"_anon_{line_no}"
            warnings.append({"type": "bibtex_missing_key",
                             "detail": f"第 {line_no} 行条目缺 key，已用占位 {key}"})
        entries.append({"key": key, "etype": etype, "fields": fields,
                        "prov": {"file": src, "line": line_no},
                        "merged_from": [], "src_format": "bibtex"})
    return entries, warnings


# ---------------------------------------------------------------- RIS 解析
RIS_MAP = {
    "AU": "author", "AF": "author", "TI": "title", "T1": "title", "BT": "title",
    "JO": "journal", "JF": "journal", "T2": "journal", "VL": "volume", "IS": "number",
    "PY": "year", "Y1": "year", "DA": "year", "DO": "doi", "UR": "url", "LK": "url",
    "PB": "publisher", "SN": "issn", "M1": "note", "N1": "note", "LA": "language",
    "KW": "keywords", "CY": "address", "AN": "accession",
    "SP": "pages", "EP": "pages", "BP": "pages",
}
RIS_TYPE = {"JOUR": "article", "JOURNAL": "article", "ART": "article",
            "BOOK": "book", "CHAP": "incollection", "CONF": "inproceedings",
            "THES": "phdthesis", "RPRT": "techreport", "ELEC": "electronic"}


def parse_ris(text, src="refs.ris"):
    entries, warnings = [], []
    cur, cur_line = None, None
    multi = ("author", "keywords")

    def finalize():
        nonlocal cur, cur_line
        if cur is not None:
            if "author" in cur["fields"]:
                cur["fields"]["author"] = " and ".join(cur["fields"]["author"])
            if "keywords" in cur["fields"]:
                cur["fields"]["keywords"] = "; ".join(cur["fields"]["keywords"])
            if "pages" in cur["fields"] and isinstance(cur["fields"]["pages"], list):
                cur["fields"]["pages"] = "-".join(cur["fields"]["pages"])
            if "year" in cur["fields"]:
                y = re.search(r"(1[89]\d{2}|20\d{2})", str(cur["fields"]["year"]))
                cur["fields"]["year"] = y.group(1) if y else cur["fields"]["year"]
            entries.append(cur)
        cur, cur_line = None, None

    for ln, line in enumerate(text.splitlines(), 1):
        m = re.match(r"^([A-Za-z][A-Za-z0-9])\s{1,3}-\s?(.*)$", line)
        if not m:
            if line.strip() and cur is not None:
                # 续行：并入上一多值字段
                for f in multi:
                    if isinstance(cur["fields"].get(f), list) and cur["fields"][f]:
                        cur["fields"][f][-1] += " " + line.strip()
            continue
        tag, val = m.group(1).upper(), m.group(2).strip()
        if tag == "TY":
            finalize()
            cur = {"key": "", "etype": RIS_TYPE.get(val.upper(), "misc"),
                   "fields": {}, "prov": {"file": src, "line": ln},
                   "merged_from": [], "src_format": "ris"}
            cur_line = ln
            cur["fields"]["_ ris_type"] = val
            continue
        if tag == "ER":
            finalize()
            continue
        if cur is None:
            warnings.append({"type": "ris_record_before_ty", "detail": f"第 {ln} 行 {tag} 出现在 TY 之前，忽略"})
            continue
        field = RIS_MAP.get(tag)
        if not field:
            continue
        if field in multi:
            cur["fields"].setdefault(field, []).append(val)
        elif field == "pages" and tag in ("SP", "EP", "BP"):
            cur["fields"].setdefault("pages", [])
            if isinstance(cur["fields"]["pages"], list):
                if tag in ("SP", "BP"):
                    cur["fields"]["pages"] = [val]
                else:
                    cur["fields"]["pages"].append(val)
        else:
            cur["fields"][field] = val
    finalize()
    for idx, e in enumerate(entries, 1):
        if not e["key"]:
            t = e["fields"].get("title") or f"ris{idx}"
            e["key"] = re.sub(r"\W+", "", t)[:24].lower() or f"ris{idx}"
        e["fields"].pop("_ ris_type", None)
    if not entries:
        warnings.append({"type": "ris_no_records", "detail": "未发现 TY/ER 记录"})
    return entries, warnings


# ---------------------------------------------------------------- 纯文本编号列表（启发式）
def parse_textlist(text, src="refs.txt"):
    entries, warnings = [], []
    for ln, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s:
            continue
        m = re.match(r"^\[?(\d{1,3})\]?\s*[.、．]?\s*(.+)$", s)
        if not m:
            continue
        num, body_txt = int(m.group(1)), m.group(2).strip()
        fields = {"raw_ref": body_txt}
        dm = re.search(r"(10\.\d{4,9}/[^\s,;，；\]]+)", body_txt)
        if dm:
            fields["doi"] = dm.group(1).rstrip(".")
        ym = re.search(r"(1[89]\d{2}|20\d{2})", body_txt)
        if ym:
            fields["year"] = ym.group(1)
        segs = [x.strip() for x in re.split(r"[.．。]\s+", body_txt) if x.strip()]
        if len(segs) >= 3:
            fields.setdefault("author", segs[0])
            fields.setdefault("title", segs[1])
        elif len(segs) == 2:
            fields.setdefault("title", segs[1])
        entries.append({"key": f"ref{num}", "etype": "misc", "fields": fields,
                        "prov": {"file": src, "line": ln},
                        "merged_from": [], "src_format": "text"})
    if entries:
        warnings.append({"type": "low_structure_format",
                         "detail": f"纯文本编号列表启发式解析 {len(entries)} 条：字段抽取不保证完整，"
                                   f"title/author 仅按句段切分，需人工复核"})
    return entries, warnings


# ---------------------------------------------------------------- JSON / CSL-JSON（启发式映射）
CSL_TYPE = {
    "article-journal": "article", "article-magazine": "article", "article-newspaper": "article",
    "paper-conference": "inproceedings", "chapter": "incollection", "book": "book",
    "thesis": "phdthesis", "report": "techreport", "webpage": "electronic", "dataset": "electronic",
}
CSL_FIELD = {
    "title": "title", "container-title": "journal", "journal": "journal", "publisher": "publisher",
    "volume": "volume", "issue": "number", "page": "pages", "DOI": "doi", "doi": "doi",
    "URL": "url", "url": "url", "ISBN": "isbn", "ISSN": "issn", "language": "language",
    "note": "note", "event-place": "address", "publisher-place": "address", "address": "address",
    "booktitle": "booktitle", "collection-title": "note",
}


def _is_json(text):
    try:
        json.loads(text)
        return True
    except (ValueError, json.JSONDecodeError):
        return False


def _json_year(v):
    """从 CSL issued / 数字 / 字符串中取 4 位年份。"""
    if isinstance(v, dict):
        dp = v.get("date-parts")
        if isinstance(dp, list) and dp and isinstance(dp[0], list) and dp[0]:
            return str(dp[0][0])
        raw = v.get("raw")
        if isinstance(raw, str):
            m = re.search(r"(1[89]\d{2}|20\d{2})", raw)
            return m.group(1) if m else None
        return None
    if isinstance(v, (int, float)):
        return str(int(v))
    if isinstance(v, str):
        m = re.search(r"(1[89]\d{2}|20\d{2})", v)
        return m.group(1) if m else v
    return None


def _json_authors(v):
    """CSL author 列表 → 'Family, Given and ...' 字符串。"""
    if isinstance(v, str):
        return v
    if not isinstance(v, list):
        return None
    out = []
    for a in v:
        if isinstance(a, str):
            out.append(a)
        elif isinstance(a, dict):
            fam, giv = a.get("family") or a.get("literal"), a.get("given")
            if fam and giv:
                out.append(f"{fam}, {giv}")
            elif fam:
                out.append(str(fam))
            elif giv:
                out.append(str(giv))
    return " and ".join(out) if out else None


def _json_entry(obj, idx, src):
    """把单个 JSON 记录映射为内部条目（CSL-JSON 或同名字段）。"""
    fields = {}
    for k, v in obj.items():
        if isinstance(v, (dict, list)) or k in ("author", "editor", "id", "type", "issued"):
            continue
        tgt = CSL_FIELD.get(k, k if k in FIELD_ORDER else None)
        if tgt and v not in (None, ""):
            fields[tgt] = str(v).strip()
    au = _json_authors(obj.get("author") or obj.get("editor"))
    if au:
        fields["author"] = au
    yr = _json_year(obj.get("issued") or obj.get("year") or obj.get("date"))
    if yr:
        fields["year"] = yr
    base = str(obj.get("type", "")).lower()
    etype = CSL_TYPE.get(base, base if base in DOC_TYPE else "misc")
    key = str(obj.get("id") or obj.get("key") or "").strip()
    if not key:
        key = (re.sub(r"\W+", "", (fields.get("title") or f"json{idx}").lower())[:24]) or f"json{idx}"
    return {"key": key, "etype": etype, "fields": fields,
            "prov": {"file": src, "line": idx, "record_index": idx},
            "merged_from": [], "src_format": "json"}


def parse_json(text, src="refs.json"):
    """解析 CSL-JSON 数组 / {references|items|data|entries:[...]} / {key: fields} 形式。"""
    entries, warnings = [], []
    try:
        data = json.loads(text)
    except (ValueError, json.JSONDecodeError) as e:
        warnings.append({"type": "json_unparseable", "detail": f"{src}: {e}"})
        return entries, warnings
    seq = None
    if isinstance(data, list):
        seq = data
    elif isinstance(data, dict):
        for k in ("references", "items", "data", "entries", "records"):
            if isinstance(data.get(k), list):
                seq = data[k]
                break
        if seq is None:  # {key: {fields}}
            seq = []
            for k, v in data.items():
                if isinstance(v, dict):
                    v = dict(v)
                    v.setdefault("id", k)
                    seq.append(v)
    if not seq:
        warnings.append({"type": "json_no_records", "detail": f"{src}: 未找到记录数组"})
        return entries, warnings
    for idx, obj in enumerate(seq, 1):
        if isinstance(obj, dict):
            entries.append(_json_entry(obj, idx, src))
    if not entries:
        warnings.append({"type": "json_no_records", "detail": f"{src}: 记录均非对象，未解析到条目"})
    return entries, warnings


def detect_and_parse(path, forced="auto"):
    text, enc = read_text(path)
    body = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("%"))
    fmt = forced
    if fmt == "auto":
        if re.search(r"@\s*[A-Za-z]+\s*[\{(]", body):
            fmt = "bibtex"
        elif re.search(r"^\s*(TY|ER)\s{1,3}-", text, re.M):
            fmt = "ris"
        elif text.lstrip()[:1] in ("[", "{") and _is_json(text):
            fmt = "json"
        else:
            fmt = "text"
    if fmt == "bibtex":
        entries, warns = parse_bibtex(text, os.path.basename(path))
    elif fmt == "ris":
        entries, warns = parse_ris(text, os.path.basename(path))
    elif fmt == "json":
        entries, warns = parse_json(text, os.path.basename(path))
    else:
        entries, warns = parse_textlist(text, os.path.basename(path))
        fmt = "text"
    return entries, warns, fmt, enc


# ---------------------------------------------------------------- 归一化 / 去重
def norm_doi(doi):
    if not doi:
        return None
    d = doi.strip().strip(".")
    d = re.sub(r"^(doi:|https?://(dx\.)?doi\.org/)", "", d, flags=re.I)
    return d.lower() or None


def valid_doi(d):
    return bool(d and re.match(r"^10\.\d{4,9}/\S+$", d))


def norm_title(t):
    if not t:
        return None
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", t.lower())
    return t or None


def split_authors(s):
    parts = re.split(r"\s+and\s+|;|；", s or "", flags=re.I)
    return [p.strip() for p in parts if p.strip()]


def first_author_surname(fields):
    aus = split_authors(fields.get("author") or "")
    if not aus:
        return None
    a = aus[0]
    if CJK_RE.search(a):
        return a[0]
    if "," in a:
        return a.split(",", 1)[0].strip().lower()
    toks = a.split()
    if len(toks) == 2:  # 拼音双词名：姓在前（与渲染启发式一致）
        return toks[0].lower()
    return (toks[-1] if toks else a).lower()


def match_pair(a, b):
    """返回 (merge_basis|None, conflict|None)。绝不因题名相同但 DOI/年份不同而合并。"""
    da, db = norm_doi(a["fields"].get("doi")), norm_doi(b["fields"].get("doi"))
    va, vb = valid_doi(da), valid_doi(db)
    ta, tb = norm_title(a["fields"].get("title")), norm_title(b["fields"].get("title"))
    same_title = ta and tb and ta == tb
    if va and vb:
        if da == db:
            return "DOI_EXACT", None
        if same_title:
            note = "疑似重复（题名一致但 DOI 不同）"
            if "arxiv" in (da + db) or "arxiv" in (a["fields"].get("note", "") + b["fields"].get("note", "")):
                note += "；含 arXiv 标识，可能为预印本/正式版，建议人工确认"
            return None, note
        return None, None
    if (da or db) and not (va and vb):
        # 仅一侧有（或仅一侧合法）DOI：不足以自动合并
        if same_title:
            ya, yb = a["fields"].get("year"), b["fields"].get("year")
            if ya and ya == yb:
                return None, "疑似重复（题名/年份一致但 DOI 不全为合法格式），不足以自动合并，建议人工确认后合并"
        return None, None
    # 两侧均无合法 DOI
    if same_title:
        ya, yb = a["fields"].get("year"), b["fields"].get("year")
        sa, sb = first_author_surname(a["fields"]), first_author_surname(b["fields"])
        if ya and yb and ya == yb and sa and sb and sa == sb:
            return "TITLE_AUTHOR_YEAR", None
        reason = []
        if ya and yb and ya != yb:
            reason.append(f"年份不同({ya} vs {yb})")
        if sa and sb and sa != sb:
            reason.append("第一作者姓不同")
        if not ya or not yb:
            reason.append("年份字段缺失")
        if not sa or not sb:
            reason.append("作者字段缺失")
        return None, "疑似重复（题名一致但" + "、".join(reason) + "），保守不合并，建议人工确认"
    return None, None


def union_fields(kept, dup):
    """字段并集策略：先取保留条目非空值；author 取更长列表；全记入 policy 供回溯。"""
    policy = {}
    for f in FIELD_ORDER:
        kv, dv = kept["fields"].get(f), dup["fields"].get(f)
        if not kv and dv:
            kept["fields"][f] = dv
            policy[f] = f"缺失，取自 {dup['key']}"
        elif kv and dv and f == "author":
            ka, da_ = split_authors(kv), split_authors(dv)
            if len(da_) > len(ka):
                policy["author_original"] = kv
                kept["fields"]["author"] = dv
                policy[f] = f"取更长作者列表 {dup['key']}（{len(ka)}→{len(da_)} 人）"
    kept["merged_from"].append(dup["key"])
    return policy


def dedupe(entries):
    """候选与**全部**保留条目逐一比较（无提前 break），合并依据可解释。"""
    kept, merges, conflicts = [], [], []
    for e in entries:
        target = None
        for k in kept:
            basis, conflict = match_pair(e, k)
            if basis:
                target = k
                policy = union_fields(k, e)
                merges.append({
                    "action": "merge", "kept": k["key"], "removed": e["key"],
                    "basis": basis,
                    "basis_detail": {
                        "DOI_EXACT": f"归一化 DOI 一致：{norm_doi(k['fields'].get('doi'))}",
                        "TITLE_AUTHOR_YEAR": "题名归一化一致 + 第一作者姓一致 + 年份一致（两侧均无合法 DOI）",
                    }[basis],
                    "field_policy": policy,
                    "removed_provenance": e["prov"],
                })
                break
            if conflict:
                conflicts.append({"keys": sorted([e["key"], k["key"]]),
                                  "disposition": "kept_separate_needs_human_review",
                                  "reason": conflict})
        if target is None:
            kept.append(e)
    # 去重 conflicts（每对只报一次）
    seen, uniq = set(), []
    for c in conflicts:
        sig = tuple(c["keys"]) + (c["reason"],)
        if sig not in seen:
            seen.add(sig)
            uniq.append(c)
    return kept, merges, uniq


# ---------------------------------------------------------------- 稿件标记
CITE_GROUP_RE = re.compile(r"\[((?:\d+)(?:\s*[,，;；]\s*\d+|\s*[-–—~～]\s*\d+)*)\]")


def expand_group(inner):
    nums = []
    for part in re.split(r"[,，;；]", inner):
        part = part.strip()
        if not part:
            continue
        rm = re.match(r"^(\d+)\s*[-–—~～]\s*(\d+)$", part)
        if rm:
            a, b = int(rm.group(1)), int(rm.group(2))
            if a <= b and b - a <= 200:
                nums.extend(range(a, b + 1))
            else:
                nums.extend([a, b])
        else:
            nums.append(int(part))
    return nums


def compact_numbers(nums):
    nums = sorted(set(nums))
    out, i = [], 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        if j - i >= 2:
            out.append(f"{nums[i]}-{nums[j]}")
        elif j == i:
            out.append(str(nums[i]))
        else:
            out.append(f"{nums[i]},{nums[i+1]}")
        i = j + 1
    return ",".join(out)


# 参考文献节识别：Markdown/加粗标题，或“裸”标题行（如“参考文献”“References:”），
# 或无标题的末尾连续编号列表（GB/T 常见形态）——先剥离再重建，避免把原稿已有文献表
# 当作正文引用重新编号并留下重复列表。
REF_HEADING_RE = re.compile(
    r"^\s*(?:#{1,6}\s*|\*{1,2}\s*)?(参考文献|references|bibliography)\s*:?\s*\*{0,2}\s*$", re.I)
REF_ENTRY_RE = re.compile(r"^\s*\[?(\d{1,3})\]?\s*[.、．)]?\s*\S")
MD_HEADING_RE = re.compile(r"^\s*(#{1,6})\s+\S")
BOLD_HEADING_RE = re.compile(r"^\s*\*{1,2}[^*\n]+\*{1,2}\s*$")
DOI_IN_TEXT_RE = re.compile(r"10\.\d{4,9}/\S+", re.I)
TYPE_BRACKET_RE = re.compile(r"\[[A-Z]{1,4}(?:/OL)?\]", re.I)
YEAR_IN_TEXT_RE = re.compile(r"(?:1[89]\d{2}|20\d{2})")
VENUE_YEAR_RE = re.compile(r"[A-Z][A-Za-z]*\.?\s*,\s*(?:1[89]\d{2}|20\d{2})")
# 正文与“参考文献标题后保留尾部（附录/图注）”之间的哨兵：无 [数字] 结构，标记处理不会改写。
TAIL_BOUNDARY = "\x00REF_TAIL_BOUNDARY\x00"


def _md_heading_level(line):
    m = MD_HEADING_RE.match(line)
    return len(m.group(1)) if m else None


def _plain_ref_entry(line):
    """返回 (编号, 编号后内容)；非编号行返回 (None, None)。"""
    s = line.strip()
    m = re.match(r"^\[?(\d{1,3})\]?\s*[.、．)]?\s*(.*)$", s)
    if not m:
        return None, None
    return int(m.group(1)), m.group(2).strip()


def _has_bib_evidence(content):
    """内容级书目证据：DOI / GB/T 类型标识 / 来源或作者+年份 / 分句作者·题名结构。
    仅连续纯数字不构成证据，避免把普通结论/配料/程序清单误判为文献表。"""
    if DOI_IN_TEXT_RE.search(content):
        return True
    if TYPE_BRACKET_RE.search(content):
        return True
    if YEAR_IN_TEXT_RE.search(content):
        if VENUE_YEAR_RE.search(content):
            return True
        segs = [x for x in re.split(r"[.．。;；]", content) if x.strip()]
        text_segs = [x for x in segs if re.search(r"[A-Za-z\u4e00-\u9fff]{2,}", x)]
        if len(text_segs) >= 2:
            return True
    return False


def find_plain_ref_block(lines):
    """无标题时从文末寻找连续编号列表块（≥2 条）的起始行号；未找到返回 None。
    判定不再要求编号从 1 起或连续，但要求块内至少两条且过半行具备内容级书目证据；
    仅凭连续纯数字的普通结论/配料/程序清单绝不剥离。"""
    i = len(lines) - 1
    while i >= 0 and not lines[i].strip():
        i -= 1
    entries = []
    while i >= 0 and lines[i].strip():
        num, content = _plain_ref_entry(lines[i])
        if num is None:
            break
        entries.append((num, content))
        i -= 1
    entries.reverse()
    if len(entries) < 2:
        return None
    evidenced = sum(1 for _, c in entries if _has_bib_evidence(c))
    if evidenced < 2 or evidenced * 2 < len(entries):
        return None
    return i + 1


def split_manuscript(text):
    """返回 (正文行, 原标题行或 None, 应保留的后续尾部行, 识别方式)。识别方式 ∈ heading/plain_list/None。

    heading：参考文献标题只剥离“该标题到下一同级或更高标题之间”的旧文献区，
    其后的附录/图注等内容原样保留（不盲删文末）。
    plain_list：无标题末尾编号列表按内容证据识别后整体剥离，其后无可保留正文。
    """
    lines = text.splitlines()
    for idx, ln in enumerate(lines):
        if REF_HEADING_RE.match(ln):
            body = lines[:idx]
            heading = ln
            level = _md_heading_level(ln)
            end = len(lines)
            for j in range(idx + 1, len(lines)):
                lj = _md_heading_level(lines[j])
                if lj is not None and (level is None or lj <= level):
                    end = j
                    break
                if level is None and BOLD_HEADING_RE.match(lines[j]):
                    end = j
                    break
            tail = lines[end:]
            return body, heading, tail, "heading"
    start = find_plain_ref_block(lines)
    if start is not None:
        return lines[:start], None, [], "plain_list"
    return lines, None, [], None


def process_manuscript(body_text, old2kept, total_old, kept_count):
    """两遍法：先按正文出现顺序分配新编号（顺序编码制），再重渲染标记。"""
    groups = []
    for m in CITE_GROUP_RE.finditer(body_text):
        if m.end() < len(body_text) and body_text[m.end()] == "(":
            continue  # 跳过 markdown 链接形如 [1](url)
        old_nums = expand_group(m.group(1))
        valid = [n for n in old_nums if n in old2kept]
        dangling = [n for n in old_nums if n not in old2kept]
        groups.append({"match": m, "old_numbers": old_nums, "valid": valid, "dangling": dangling})

    numbering = {}
    counter = 0
    for g in groups:
        for old in g["valid"]:
            kidx = old2kept[old]
            if kidx not in numbering:
                counter += 1
                numbering[kidx] = counter
    for kidx in range(kept_count):  # 未引用条目按原序补在末尾
        if kidx not in numbering:
            counter += 1
            numbering[kidx] = counter
    old2new = {old: numbering[kidx] for old, kidx in old2kept.items()}

    out, last = [], 0
    for g in groups:
        m = g["match"]
        new_nums = [old2new[o] for o in g["valid"]]
        rendered_inner = compact_numbers(new_nums + g["dangling"])
        rendered = f"[{rendered_inner}]"
        out.append(body_text[last:m.start()])
        out.append(rendered)
        last = m.end()
        g.pop("match")
        g["original"] = m.group(0)
        g["new_numbers"] = new_nums
        g["rendered"] = rendered
        g["dangling_flag"] = bool(g["dangling"])
    out.append(body_text[last:])
    return "".join(out), groups, old2new, numbering


# ---------------------------------------------------------------- GB/T 7714 渲染
def fmt_author_gbt(name):
    name = re.sub(r"[{}]", "", name).strip()
    if not name:
        return None
    if CJK_RE.search(name):
        return name
    if "," in name:
        fam, giv = name.split(",", 1)
    else:
        toks = name.split()
        if len(toks) == 1:
            return toks[0].upper()
        if len(toks) == 2:  # 拼音双词名按“姓 前 名 后”处理（中文文献库惯例）
            fam, giv = toks[0], toks[1]
        else:               # 西文多词名按“名 前 姓 后”
            fam, giv = toks[-1], " ".join(toks[:-1])
    initials = " ".join(t[0].upper() for t in giv.split() if t)
    return (fam.upper() + (" " + initials if initials else "")).strip()


_ETAL_MARKERS = ("et al.", "et al", "et alii", "etc.", "etc", "others", "and others", "等人", "等")


def _split_etal_marker(name):
    """仅识别末段为/以明确截断标记结尾的形态，返回 (真实作者名或 None, 是否截断)。
    不拆分正常姓名；作者恰好姓 Others 的罕见歧义不在此自动判定，保留人工复核边界。"""
    s = name.strip()
    if not s:
        return None, False
    low = s.lower()
    if low in {m.lower() for m in _ETAL_MARKERS}:
        return None, True
    for m in _ETAL_MARKERS:
        ml = m.lower()
        if low.endswith(ml):
            pre = s[:len(s) - len(m)].rstrip().rstrip(",;；").strip()
            return (pre or None), True
    return s, False


def fmt_authors_gbt(fields):
    aus = split_authors(fields.get("author") or "")
    if not aus:
        return "（作者字段缺失）"
    cjk = any(CJK_RE.search(a) for a in aus)
    truncated = False
    new_last, tr = _split_etal_marker(aus[-1])
    if tr:
        truncated = True
        aus = (aus[:-1] + [new_last]) if new_last else aus[:-1]
    fmt = [fmt_author_gbt(a) for a in aus]
    fmt = [f for f in fmt if f]
    if not fmt:
        return "（作者字段缺失）"
    etal = "等" if cjk else "et al"
    if truncated:
        return ", ".join(fmt) + ", " + etal + "."
    if len(fmt) > 3:
        return ", ".join(fmt[:3]) + ", " + etal + "."
    return ", ".join(fmt) + "."


def gbt7714_line(entry, number, uncited=False):
    f = entry["fields"]
    au = fmt_authors_gbt(f)
    title = f.get("title") or f"（条目 {entry['key']} 缺 title 字段，未虚构）"
    code = DOC_TYPE.get(entry["etype"], "Z")
    place = f.get("address") or f.get("place") or f.get("location")
    venue = f.get("journal") or f.get("booktitle") or f.get("publisher") \
        or f.get("school") or f.get("institution")
    if place and code in ("M", "C", "G", "R", "D", "P"):
        venue = f"{place}: {venue}" if venue else place
    year = f.get("year")
    parts = [f"[{number}] {au} {title}[{code}]."]
    if venue:
        seg = venue
        if year:
            seg += f", {year}"
        if f.get("volume"):
            seg += f", {f['volume']}"
            if f.get("number"):
                seg += f"({f['number']})"
        elif f.get("number"):
            seg += f"({f['number']})"
        if f.get("pages"):
            pages_gbt = re.sub(r"--+|[–—〜~]", "-", f["pages"])
            seg += f": {pages_gbt}"
        parts.append(f" {seg}.")
    elif year:
        parts.append(f" {year}.")
    else:
        parts.append(" （卷期页/来源字段缺失）.")
    doi = norm_doi(f.get("doi"))
    if valid_doi(doi):
        parts.append(f" DOI: {doi}.")
    if f.get("url") and entry["etype"] in ("electronic", "online", "misc") and not venue:
        parts.append(f" {f['url']}.")
    line = "".join(parts)
    if uncited:
        line += "（未在正文引用）"
    return line


# ---------------------------------------------------------------- DOI 在线核验（可选）
def verify_dois(dois, mode):
    if mode != "online":
        return {d: {"verification": "not_attempted",
                    "detail": "默认离线模式；如需在线核验请加 --verify-doi online"} for d in dois}
    results = {}
    import urllib.request
    import urllib.error  # noqa: F401
    for d in list(dois)[:50]:
        url = f"https://doi.org/api/handles/{d}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": f"{SKILL_NAME}/{VERSION} citation-check"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                ok = b'"handle"' in resp.read(4096)
                results[d] = {"verification": "verified" if ok else "uncertain",
                              "detail": f"doi.org handle API HTTP {resp.status}"}
        except urllib.error.HTTPError as e:
            results[d] = {"verification": "not_found" if e.code == 404 else "http_error",
                          "detail": f"HTTP {e.code}"}
        except Exception as e:  # noqa: BLE001
            results[d] = {"verification": "network_error", "detail": str(e)[:200]}
    if len(dois) > 50:
        results["_note"] = {"verification": "capped", "detail": f"超过 50 条上限，仅核验前 50 条（共 {len(dois)}）"}
    return results


# ---------------------------------------------------------------- 主流程
def run(argv=None):
    ap = argparse.ArgumentParser(description=f"参考文献与引用管理确定性管线 v{VERSION}")
    ap.add_argument("--manuscript", help="稿件 Markdown/纯文本路径")
    ap.add_argument("--refs", help="文献库路径（BibTeX/RIS/CSL-JSON/纯文本编号列表，自动识别）")
    ap.add_argument("--case", help="case.json 路径（用于 case_id 与 output_contract 镜像）")
    ap.add_argument("--outdir", default="out", help="输出目录（默认 ./out）")
    ap.add_argument("--refs-format", choices=["auto", "bibtex", "ris", "json", "text"], default="auto",
                    help="强制指定文献库格式（默认 auto：按内容自动识别）")
    ap.add_argument("--style", choices=["gbt7714-2015-numeric"], default="gbt7714-2015-numeric",
                    help="当前版本仅实现 GB/T 7714—2015 顺序编码制")
    ap.add_argument("--verify-doi", choices=["off", "online"], default="off",
                    help="DOI 在线核验默认关闭（评测环境联网情况未知，离线降级为 not_attempted）")
    args = ap.parse_args(argv)

    warnings, encoding_notes = [], []
    case, case_enc = (None, None)
    if args.case:
        case, case_enc = load_case(args.case, warnings)
        if case_enc:
            encoding_notes.append(f"case.json 以 {case_enc} 读取")

    ms_path, refs_path = args.manuscript, args.refs
    if (not ms_path or not refs_path) and case:
        c_ms, c_refs = case_inputs(case, os.path.dirname(os.path.abspath(args.case)))
        ms_path = ms_path or c_ms
        refs_path = refs_path or c_refs

    outdir = os.path.abspath(args.outdir)
    os.makedirs(outdir, exist_ok=True)

    def finish(status, exit_code, extra=None):
        result = build_result(args, case, status, warnings, encoding_notes,
                              ms_path, refs_path, outdir, extra or {})
        result_path = os.path.join(outdir, "result.json")
        write_text(result_path, json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps({"status": status, "exit": exit_code,
                          "result_json": result_path}, ensure_ascii=False))
        return exit_code

    missing = [p for p in (ms_path, refs_path) if not p or not os.path.isfile(p)]
    if missing:
        warnings.append({"type": "input_missing",
                         "detail": f"输入缺失：{missing}；无法运行核心管线"})
        return finish("failed", 2)

    ms_text, ms_enc = read_text(ms_path)
    encoding_notes.append(f"{os.path.basename(ms_path)} 以 {ms_enc} 读取")
    entries, parse_warnings, refs_fmt, refs_enc = detect_and_parse(refs_path, args.refs_format)
    warnings.extend(parse_warnings)
    encoding_notes.append(f"{os.path.basename(refs_path)} 以 {refs_enc} 读取（识别格式 {refs_fmt}）")
    if not entries:
        warnings.append({"type": "no_entries_parsed",
                         "detail": f"{refs_path} 未解析到任何条目（格式 {refs_fmt}）"})

    # 去重归并
    kept, merges, conflicts = dedupe(entries)
    total_old = len(entries)

    # 稿件标记处理：正文与“参考文献标题后的附录/尾部内容”合并处理（共享编号），
    # 参考文献旧区（标题到下一同级/更高标题之间）整体剥离重建。
    body_lines, ref_heading, tail_lines, ref_mode = split_manuscript(ms_text)
    existing_ref_section = {"detected": ref_mode is not None, "mode": ref_mode}
    if ref_mode == "plain_list":
        warnings.append({"type": "existing_reference_section_rebuilt",
                         "detail": "原稿末尾检测到无标题的编号参考文献列表，已剥离并按新编号重建；"
                                   "不把已有文献表当作正文引用重新编号，也不保留重复列表"})
    body_text = "\n".join(body_lines)
    # 旧编号→保留条目下标；被合并条目改指其保留条目（如 [7]→dup1 已并入 zhang2020a）
    key2kept_idx = {k["key"]: i for i, k in enumerate(kept)}
    removed2kept_key = {m["removed"]: m["kept"] for m in merges}
    old2kept = {}
    for old_idx, e in enumerate(entries, 1):
        if e in kept:
            old2kept[old_idx] = kept.index(e)
        elif removed2kept_key.get(e["key"]) in key2kept_idx:
            old2kept[old_idx] = key2kept_idx[removed2kept_key[e["key"]]]
    tail_text = "\n".join(tail_lines).strip() if tail_lines else ""
    if tail_text:
        combined = body_text.rstrip() + "\n\n" + TAIL_BOUNDARY + "\n\n" + tail_text
        new_combined, groups, old2new, numbering = process_manuscript(
            combined, old2kept, total_old, len(kept))
        new_body, _, new_tail = new_combined.partition(TAIL_BOUNDARY)
        new_body = new_body.rstrip()
        new_tail = new_tail.strip()
    else:
        new_body, groups, old2new, numbering = process_manuscript(
            body_text, old2kept, total_old, len(kept))
        new_tail = ""
    cited_kept = {v for g in groups for v in g["new_numbers"]}

    dangling_groups = [g for g in groups if g["dangling_flag"]]
    for g in dangling_groups:
        warnings.append({"type": "dangling_citation",
                         "detail": f"标记 {g['original']}（渲染为 {g['rendered']}）指向不存在的条目 "
                                   f"{g['dangling']}（文献库仅 {total_old} 条）；正文原样保留，未删句未改写"})

    # DOI 校验/核验
    all_dois = sorted({norm_doi(e["fields"].get("doi")) for e in kept
                       if valid_doi(norm_doi(e["fields"].get("doi")))})
    invalid_doi_items = [{"key": e["key"], "doi_raw": e["fields"].get("doi")}
                         for e in kept if e["fields"].get("doi") and not valid_doi(norm_doi(e["fields"].get("doi")))]
    for it in invalid_doi_items:
        warnings.append({"type": "invalid_doi_format",
                         "detail": f"条目 {it['key']} 的 DOI “{it['doi_raw']}” 不符合 10.xxxx/后缀 格式，"
                                   f"标记为不可核验（离线降级），不渲染为 DOI，不声称已核验"})
    doi_results = verify_dois(all_dois, args.verify_doi)

    uncited = [numbering[i] for i in range(len(kept)) if numbering[i] not in cited_kept]
    for num in uncited:
        warnings.append({"type": "uncited_entry",
                         "detail": f"条目编号 {num}（{kept[[numbering[i] for i in range(len(kept))].index(num)]['key']}）"
                                   f"未在正文引用，已在文献表标注“未在正文引用”"})

    # 正文—文献表双向一致性检查（对得上）
    list_numbers = sorted(numbering[i] for i in range(len(kept)))
    body_valid = sorted({n for g in groups for n in g["new_numbers"]})
    dangling_numbers = sorted({n for g in groups for n in g["dangling"]})
    missing_in_list = [n for n in body_valid if n not in list_numbers]
    list_without_body = [n for n in list_numbers if n not in body_valid]
    consistency = {
        "policy": "正文有效标记 ⊆ 文献表编号，未被正文引用的条目必须显式标注，且正文不得残留悬空（dangling）标记",
        "body_valid_numbers": body_valid,
        "list_numbers": list_numbers,
        "dangling_numbers": dangling_numbers,
        "body_numbers_missing_from_list": missing_in_list,
        "list_numbers_without_body_citation": list_without_body,
        "uncited_numbers": uncited,
        "ok": (not missing_in_list and not dangling_numbers
               and sorted(list_without_body) == sorted(uncited)),
    }
    if not consistency["ok"]:
        warnings.append({"type": "consistency_check_failed",
                         "detail": f"正文与文献表未闭合：missing_in_list={missing_in_list} "
                                   f"dangling_numbers={dangling_numbers} "
                                   f"list_without_body={list_without_body} uncited={uncited}"})
    # 渲染文献表：按新编号升序排列，条目/行/编号三列严格对齐（不再把已排序序列与 kept 下标 zip 错位）
    order = sorted(range(len(kept)), key=lambda i: numbering[i])
    kept_sorted = [kept[i] for i in order]
    kept_sorted_nums = [numbering[i] for i in order]
    ref_lines = [gbt7714_line(kept[i], numbering[i], uncited=(numbering[i] in uncited))
                 for i in order]
    num_of_kept = [numbering[i] for i in range(len(kept))]

    # 输出：改稿（正文重编号 + 重建参考文献节 + 标注注释块）
    annotation_lines = [f"<!-- 引用管理标注（{SKILL_NAME} citation_pipeline v{VERSION} 自动生成；"
                        f"正文论断未作任何改写，仅更新引用编号与文献表；逐条依据见同目录 result.json）"]
    if dangling_groups:
        annotation_lines.append("- 超出文献库范围的引用标记（dangling，已原样保留）："
                                + "；".join(f"{g['original']}→{g['rendered']} 指向 {g['dangling']}" for g in dangling_groups))
    if conflicts:
        annotation_lines.append("- 疑似重复但未合并（保守策略，需人工确认）："
                                + "；".join(f"{c['keys']}（{c['reason']}）" for c in conflicts))
    if invalid_doi_items:
        annotation_lines.append("- DOI 格式异常（不可核验，未渲染为 DOI）："
                                + "；".join(f"{it['key']} = {it['doi_raw']}" for it in invalid_doi_items))
    if uncited:
        annotation_lines.append(f"- 未被正文引用的条目编号：{uncited}（已在文献表标注）")
    if merges:
        annotation_lines.append("- 已合并重复条目：" + "；".join(
            f"{m['removed']} 并入 {m['kept']}（依据 {m['basis']}：{m['basis_detail']}）" for m in merges))
    if not any(len(a) > 2 for a in annotation_lines[1:]):
        annotation_lines.append("- 无 dangling、无冲突、无 DOI 异常、无未引用条目")
    annotation_lines.append("-->")

    heading = ref_heading.rstrip() if ref_heading else "## 参考文献"
    if new_tail:
        updated_ms = "\n".join([new_body, "", heading] + ref_lines + ["", new_tail, ""] + annotation_lines) + "\n"
    else:
        updated_ms = "\n".join([new_body.rstrip(), "", heading] + ref_lines + [""] + annotation_lines) + "\n"
    ms_out = os.path.join(outdir, "manuscript.updated.md")
    refs_out = os.path.join(outdir, "references.gbt7714.md")
    write_text(ms_out, updated_ms)
    write_text(refs_out, "\n".join(ref_lines) + "\n")

    status = "completed-with-warnings" if warnings else "completed"
    return finish(status, 0, {
        "entries": entries, "kept": kept, "merges": merges, "conflicts": conflicts,
        "groups": groups, "old2new": old2new, "numbering": numbering,
        "refs_fmt": refs_fmt, "doi_results": doi_results,
        "invalid_doi_items": invalid_doi_items, "uncited": uncited,
        "ref_lines": ref_lines, "files": [ms_out, refs_out],
        "kept_sorted": kept_sorted, "kept_sorted_nums": kept_sorted_nums,
        "consistency": consistency,
        "existing_ref_section": existing_ref_section,
        "ms_sha": sha256_file(ms_path), "refs_sha": sha256_file(refs_path),
        "num_of_kept": num_of_kept,
    })


def build_result(args, case, status, warnings, encoding_notes, ms_path, refs_path, outdir, x):
    contract = (case or {}).get("output_contract")
    contract_resolution = {}
    if isinstance(contract, dict):
        defaults = {
            "manuscript_updated": os.path.join(outdir, "manuscript.updated.md"),
            "references_list": os.path.join(outdir, "references.gbt7714.md"),
            "result_json": os.path.join(outdir, "result.json"),
            "style": STYLE,
        }
        for k in contract:
            if k in defaults and status != "failed":
                contract_resolution[k] = defaults[k]
            elif k == "result_json_required_fields":
                req = contract[k] if isinstance(contract[k], list) else []
                contract_resolution[k] = {f: (f in {"case_id", "status", "main_result", "sources",
                                                    "uncertainty", "changes"} and status != "failed")
                                          for f in req}
            else:
                contract_resolution[k] = None

    kept = x.get("kept", [])
    numbering = x.get("numbering", {})
    sources = []
    for i, e in enumerate(kept, 0):
        num = numbering.get(i)
        d = norm_doi(e["fields"].get("doi"))
        chk = x.get("doi_results", {}).get(d) if valid_doi(d) else None
        if not chk:
            if e["fields"].get("doi") and not valid_doi(d):
                chk = {"verification": "invalid_format_not_verifiable",
                       "detail": f"原始 DOI “{e['fields'].get('doi')}” 格式非法，离线降级为不可核验"}
            else:
                chk = {"verification": "not_applicable_no_doi", "detail": "条目无 DOI 字段"}
        sources.append({
            "number": num, "key": e["key"], "merged_from": e["merged_from"],
            "provenance": e["prov"], "entry_type": e["etype"], "source_format": e["src_format"],
            "fields": e["fields"],
            "doi_check": {"doi": d or e["fields"].get("doi"), **chk},
        })

    uncertainty = [dict(w) for w in warnings] + [
        {"type": "scope", "detail": "本管线聚焦编号更新/去重归并/来源核验（离线优先）；"
                                    "著者-出版年制、脚注制、EndNote/CNKI 专有导出、PDF 解析未实现"},
        {"type": "claim_level_check", "detail": "正文论断与文献主题的逐句匹配为人工/LLM 复核项，"
                                                "本确定性管线不做语义判定，不虚构匹配结论"},
        {"type": "known_semantic_limits", "detail": "合并会议版+预印本时正式会场可能被预印本来源取代；"
                                                "已渲染产物二次运行不保证幂等；行内编号枚举会被当作引用。"
                                                "以上为已知语义限制，转人工复核，不做硬规则自动判定"},
    ]

    changes = list(x.get("merges", []))
    for g in x.get("groups", []):
        changes.append({"action": "renumber_marker", "original": g["original"],
                        "rendered": g["rendered"],
                        "old_numbers": g["old_numbers"], "new_numbers": g["new_numbers"],
                        "dangling": g["dangling_flag"]})
    changes.append({"action": "rebuild_reference_list", "policy":
                    "顺序编码制：按正文首次引用顺序编号，未引用条目按原序补后并标注",
                    "entries": len(kept)})
    changes.append({"action": "render_style", "style": STYLE,
                    "note": "仅渲染格式合法的 DOI；作者>3 截断为前3+et al/等；缺字段如实标注不虚构"})
    for f in x.get("files", []):
        changes.append({"action": "write_file", "path": f})

    main_result = {
        "manuscript_updated": os.path.join(outdir, "manuscript.updated.md") if status != "failed" else None,
        "references_list": os.path.join(outdir, "references.gbt7714.md") if status != "failed" else None,
        "result_json": os.path.join(outdir, "result.json"),
        "style_applied": STYLE,
        "entries_parsed": len(x.get("entries", [])),
        "entries_after_merge": len(kept),
        "merges": x.get("merges", []),
        "duplicate_conflicts_unmerged": x.get("conflicts", []),
        "renumbering_policy": "正文首次引用顺序优先；未引用条目按文献库原序补在列表末尾",
        "citation_groups": [{k: v for k, v in g.items()} for g in x.get("groups", [])],
        "reference_list": [
            {"number": num, "keys": [e["key"]] + e["merged_from"],
             "gbt7714": line,
             "cited": num not in x.get("uncited", [])}
            for num, e, line in zip(
                x.get("kept_sorted_nums", [numbering.get(i) for i in range(len(kept))]),
                x.get("kept_sorted", kept), x.get("ref_lines", []))],
        "dangling_citations": [g for g in x.get("groups", []) if g["dangling_flag"]],
        "uncited_entries": x.get("uncited", []),
        "consistency": x.get("consistency"),
        "existing_reference_section": x.get("existing_ref_section"),
    }

    result = {
        "case_id": (case or {}).get("case_id"),
        "generated_by": f"{SKILL_NAME}/scripts/citation_pipeline.py v{VERSION}（确定性、默认离线、无预制答案）",
        "generated_at": utc_now(),
        "status": status,
        "input": {
            "manuscript": {"path": os.path.abspath(ms_path) if ms_path else None,
                           "sha256": x.get("ms_sha")},
            "refs": {"path": os.path.abspath(refs_path) if refs_path else None,
                     "sha256": x.get("refs_sha")},
            "refs_format_detected": x.get("refs_fmt"),
            "encoding_notes": encoding_notes,
        },
        "main_result": main_result,
        "sources": sources,
        "uncertainty": uncertainty,
        "changes": changes,
        "consistency": x.get("consistency"),
        "warnings": warnings,
        "output_contract": contract if contract is not None else {
            "status": "not_provided",
            "note": "未提供 --case / case.json 中无 output_contract；不伪造合同镜像"},
        "output_contract_resolution": contract_resolution or {
            "status": "not_provided", "note": "无 output_contract 可解析"},
        "result_json_required_fields_check": contract_resolution.get("result_json_required_fields"),
        "metrics": {
            "entries_parsed": len(x.get("entries", [])),
            "entries_after_merge": len(kept),
            "merges": len(x.get("merges", [])),
            "citation_groups": len(x.get("groups", [])),
            "markers_updated": len(x.get("groups", [])),
            "dangling_groups": len([g for g in x.get("groups", []) if g["dangling_flag"]]),
            "duplicate_conflicts_unmerged": len(x.get("conflicts", [])),
            "invalid_doi": len(x.get("invalid_doi_items", [])),
            "uncited_entries": len(x.get("uncited", [])),
            "consistency_ok": (x.get("consistency") or {}).get("ok"),
            "doi_online_verification": args.verify_doi if hasattr(args, "verify_doi") else "off",
        },
        "self_check": "python scripts/selfcheck.py 可复跑本管线不变量自检（单行条目、去重次序回归、BOM、合同镜像等）",
    }
    return result


def main():
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    sys.exit(run())


if __name__ == "__main__":
    main()
