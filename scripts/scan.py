#!/usr/bin/env python3
"""发布前词面预检：定位复核候选，不下违规结论。

输出三类结果：
  1. 风险候选 —— 内置规则词面命中（词、位置、对应规则、优先级）
  2. 我的规则 —— data/my-rules.md 黑名单命中（白名单命中会标记降噪）
  3. 辟谣提示 —— 检测到没必要的自我审查写法（如"赚米"）

用法：
  python3 scripts/scan.py --file 稿件.txt [--commercial] [--industry medical,finance] [--json]
  python3 scripts/scan.py --text "……"

词面命中只是"哪里值得看"，结论必须由语义判定得出（见 references/judgment.md）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
TERMS_PATH = SKILL_ROOT / "scripts" / "terms.json"
MY_RULES_PATH = SKILL_ROOT / "data" / "my-rules.md"
WORDLISTS_DIR = SKILL_ROOT / "data" / "wordlists"

SEVERITY_ORDER = {"critical": 4, "high": 3, "medium": 2, "low": 1}
SEVERITY_ZH = {"critical": "极高", "high": "高", "medium": "中", "low": "低"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="发布前词面预检")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path, help="UTF-8 文本文件")
    source.add_argument("--text", help="直接传入文本")
    parser.add_argument("--commercial", action="store_true", help="内容有商业属性（带货/卖课/广告/引流）")
    parser.add_argument("--industry", default="", help="逗号分隔的行业：medical,finance")
    parser.add_argument("--json", action="store_true", help="输出 JSON（默认输出 markdown）")
    parser.add_argument("--context", type=int, default=24, help="命中上下文半径字符数")
    return parser.parse_args()


def load_text(args: argparse.Namespace) -> str:
    if args.text is not None:
        return args.text
    try:
        return args.file.read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"无法读取文件: {exc}") from exc


def load_terms() -> dict:
    try:
        return json.loads(TERMS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"无法加载内置词表 {TERMS_PATH}: {exc}") from exc


INDUSTRY_ALIASES = {
    "medical": {"medical", "medical_beauty", "health_food", "pharma", "医疗", "健康"},
    "finance": {"finance", "金融", "理财"},
}


def rule_applies(term: dict, commercial: bool, industries: set[str]) -> bool:
    if term.get("commercial_only") and not commercial:
        return False
    rule_industries = set(term.get("industries", []))
    if rule_industries:
        declared: set[str] = set()
        for ind in industries:
            declared |= INDUSTRY_ALIASES.get(ind, {ind})
        return bool(rule_industries & declared)
    return True


def parse_my_rules() -> tuple[list[dict], list[dict], list[str]]:
    """解析 data/my-rules.md：黑名单表、白名单表、语义笔记。格式错误的行跳过并提示。"""
    blacklist: list[dict] = []
    whitelist: list[dict] = []
    warnings: list[str] = []
    if not MY_RULES_PATH.is_file():
        return blacklist, whitelist, warnings
    section = ""
    for line_no, raw in enumerate(MY_RULES_PATH.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if line.startswith("#"):
            if "黑名单" in line:
                section = "black"
            elif "白名单" in line:
                section = "white"
            elif line.startswith("#"):
                section = "notes" if "语义笔记" in line else ""
            continue
        if not line.startswith("|") or set(line) <= {"|", "-", " ", ":"}:
            continue
        # 表格内正则的"或"需写作 \|（裸 | 会被表格切列）；解析时还原
        placeholder = "\x00PIPE\x00"
        cells = [
            c.strip().replace(placeholder, "|")
            for c in line.strip("|").replace("\\|", placeholder).split("|")
        ]
        if cells and cells[0] in {"词/正则", "词", "词/表达"}:
            continue
        if section == "black":
            if not cells or not cells[0]:
                continue
            try:
                re.compile(cells[0])
            except re.error:
                warnings.append(f"my-rules.md 第{line_no}行黑名单正则无效，已跳过: {cells[0]}")
                continue
            blacklist.append(
                {
                    "pattern": cells[0],
                    "reason": cells[1] if len(cells) > 1 else "",
                    "platforms": cells[2] if len(cells) > 2 else "全部",
                    "level": cells[3] if len(cells) > 3 else "中",
                    "mode": (
                        "direct"
                        if len(cells) > 4 and "见词即报" in cells[4]
                        else "semantic"
                    ),
                }
            )
        elif section == "white":
            if not cells or not cells[0]:
                continue
            whitelist.append(
                {"term": cells[0], "context": cells[1] if len(cells) > 1 else ""}
            )
    return blacklist, whitelist, warnings


def load_wordlists() -> list[dict]:
    """data/wordlists/ 下的 .md/.txt 词库：一行一词，可用 | 或 TAB 附原因。

    # 开头的行是说明（恰好也是 markdown 标题），空行忽略；README 不参与解析。
    """
    entries: list[dict] = []
    if not WORDLISTS_DIR.is_dir():
        return entries
    files = sorted(
        p
        for suffix in ("*.md", "*.txt")
        for p in WORDLISTS_DIR.glob(suffix)
        if not p.name.lower().startswith("readme")
    )
    for path in files:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith("<!--"):
                continue
            parts = re.split(r"[|\t]", line, maxsplit=1)
            term = parts[0].strip("- ").strip()
            if not term:
                continue
            entries.append(
                {
                    "pattern": re.escape(term),
                    "reason": (parts[1].strip() if len(parts) > 1 else f"词库 {path.stem}"),
                    "platforms": "全部",
                    "level": "中",
                }
            )
    return entries


def find_hits(text: str, pattern: str, radius: int) -> list[dict]:
    hits = []
    try:
        compiled = re.compile(pattern, re.IGNORECASE)
    except re.error:
        return hits
    for match in compiled.finditer(text):
        start, end = match.start(), match.end()
        left = max(0, start - radius)
        right = min(len(text), end + radius)
        snippet = re.sub(r"\s+", " ", text[left:right]).strip()
        hits.append(
            {
                "match": match.group(0),
                "start": start,
                "end": end,
                "line": text.count("\n", 0, start) + 1,
                "context": ("…" if left else "") + snippet + ("…" if right < len(text) else ""),
            }
        )
    return hits


def scan(text: str, commercial: bool, industries: set[str], radius: int) -> dict:
    terms = load_terms()
    blacklist, whitelist, warnings = parse_my_rules()
    white_terms = {w["term"] for w in whitelist}

    candidates = []
    for term in terms["terms"]:
        if not rule_applies(term, commercial, industries):
            continue
        for hit in find_hits(text, term["pattern"], radius):
            muted = hit["match"] in white_terms
            candidates.append(
                {
                    **hit,
                    "rule": term["rule"],
                    "title": term["title"],
                    "severity": term["severity"],
                    "doc": term["doc"],
                    "muted_by_whitelist": muted,
                }
            )
    candidates.sort(key=lambda h: (-SEVERITY_ORDER.get(h["severity"], 0), h["start"]))

    personal = []
    seen_spans: set[tuple[int, int, str]] = set()
    for rule in blacklist + load_wordlists():
        for hit in find_hits(text, rule["pattern"], radius):
            key = (hit["start"], hit["end"], hit["match"])
            if key in seen_spans:
                continue
            seen_spans.add(key)
            personal.append(
                {
                    **hit,
                    "reason": rule["reason"],
                    "level": rule["level"],
                    "mode": rule.get("mode", "semantic"),
                }
            )
    personal.sort(key=lambda h: h["start"])

    myths = []
    for myth in terms.get("debunked_myths", []):
        for hit in find_hits(text, myth["pattern"], radius):
            myths.append({**hit, "myth": myth["myth"], "note": myth["note"], "suggestion": myth.get("suggestion", "")})

    return {
        "characters": len(text),
        "commercial": commercial,
        "industries": sorted(industries),
        "candidates": candidates,
        "personal_hits": personal,
        "myth_advisories": myths,
        "warnings": warnings,
        "note": "词面命中只是复核候选，不是违规结论；零命中也不代表语义安全。",
    }


def render_markdown(result: dict) -> str:
    lines = [
        "# 词面预检结果",
        "",
        f"- 扫描 {result['characters']} 字｜商业属性：{'有' if result['commercial'] else '无/未声明'}"
        f"｜行业：{('、'.join(result['industries']) or '通用')}",
        f"- 风险候选 {len(result['candidates'])} 处｜我的规则命中 {len(result['personal_hits'])} 处"
        f"｜辟谣提示 {len(result['myth_advisories'])} 处",
        f"- {result['note']}",
        "",
    ]
    for warning in result["warnings"]:
        lines.append(f"> ⚠ {warning}")
    if result["candidates"]:
        lines += ["## 风险候选（逐条进语义判定）", "", "| 级别 | 命中 | 行 | 上下文 | 规则 | 白名单降噪 |", "|---|---|---|---|---|---|"]
        for c in result["candidates"]:
            lines.append(
                f"| {SEVERITY_ZH.get(c['severity'], c['severity'])} | `{c['match']}` | L{c['line']} "
                f"| {c['context']} | {c['rule']}｜{c['title']} | {'是' if c['muted_by_whitelist'] else ''} |"
            )
        lines.append("")
    if result["personal_hits"]:
        lines += ["## 我的规则命中", "", "| 命中 | 行 | 上下文 | 我的备注 | 级别 | 判法 |", "|---|---|---|---|---|---|"]
        for p in result["personal_hits"]:
            mode = "见词即报" if p.get("mode") == "direct" else "语境判"
            lines.append(
                f"| `{p['match']}` | L{p['line']} | {p['context']} | {p['reason']} | {p['level']} | {mode} |"
            )
        lines.append("")
    if result["myth_advisories"]:
        lines += ["## 辟谣提示（不用改的，别自我审查）", ""]
        for m in result["myth_advisories"]:
            lines.append(f"- L{m['line']} `{m['match']}`：{m['note']} 建议：{m['suggestion']}")
        lines.append("")
    if not (result["candidates"] or result["personal_hits"] or result["myth_advisories"]):
        lines.append("未发现词面候选。仍需按 judgment.md 做全文语义检查。")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    text = load_text(args)
    industries = {i.strip() for i in args.industry.split(",") if i.strip()}
    result = scan(text, args.commercial, industries, max(0, args.context))
    if args.json:
        json.dump(result, sys.stdout, ensure_ascii=False, indent=1)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(render_markdown(result) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
