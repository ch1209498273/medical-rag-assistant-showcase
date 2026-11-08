#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""闸门③ 逐 claim 核验 · 脱敏参考实现。

对应生产系统的三道闸门中的最后一道：把答案拆成断言，逐条回查证据。
- 硬门禁：每条引用的 quote 去空白后必须逐字出现在所引切片原文里，
  指不回去 = 引用断裂 = 整条拒答（固定原因码 UNSUPPORTED_CLAIM）。
- 诊断口径：claim 文本本身是否逐字出现在证据里，只输出信号，不参与准入。
- 证据闭包：金标必达清单（多跳）缺任何一项，整条拒答（INSUFFICIENT_COVERAGE）。

只依赖标准库。数据为合成样例，见 data/ 目录。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

DATA_DIR = Path(__file__).parent / "data"

# 固定原因码：失败归因到固定类别，不给人一段含糊的解释
REASON_TIMEOUT = "TIMEOUT"
REASON_STRUCTURE = "STRUCTURE_INVALID"
REASON_UNSUPPORTED = "UNSUPPORTED_CLAIM"
REASON_COVERAGE = "INSUFFICIENT_COVERAGE"
REASON_OUT_OF_SCOPE = "OUT_OF_SCOPE"


def normalize(text: str) -> str:
    """去空白逐字比对口径：删除全部空白（含全角空格）后比较。"""
    return "".join(text.split())


def load_fragments(path: Path | None = None) -> Dict[str, Dict[str, Any]]:
    """加载切片库：id -> {doc, chapter, page, text}。"""
    path = path or DATA_DIR / "fragments.sample.jsonl"
    fragments: Dict[str, Dict[str, Any]] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            fragments[rec["id"]] = rec
    return fragments


def check_citation(citation: Dict[str, Any], fragments: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """引用逐字比对：quote 必须命中所引切片原文。"""
    fid = citation.get("fragment_id", "")
    frag = fragments.get(fid)
    if frag is None:
        return {"fragment_id": fid, "grounded": False, "reason": "fragment_not_found"}
    norm_quote = normalize(citation.get("quote", ""))
    if not norm_quote:
        return {"fragment_id": fid, "grounded": False, "reason": "empty_quote"}
    grounded = norm_quote in normalize(frag["text"])
    return {
        "fragment_id": fid,
        "grounded": grounded,
        "reason": None if grounded else "quote_not_in_fragment",
    }


def verify_answer(
    answer: Dict[str, Any],
    case: Dict[str, Any],
    fragments: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """对一条 answer 形态的输出执行闸门③。任何一项不过 → 整条拒答。"""
    claims = answer.get("claims", [])
    result: Dict[str, Any] = {
        "case_id": case["id"],
        "decision": "publish",
        "reason_code": None,
        "citation_checks": [],
        "claim_verbatim_coverage": [],  # 诊断口径，不参与准入
        "closure_ok": True,
    }

    # 闸门③-a：逐条引用回查
    for i, claim in enumerate(claims):
        citations = claim.get("citations", [])
        if not citations:
            result["decision"] = "refuse"
            result["reason_code"] = REASON_UNSUPPORTED
            result["citation_checks"].append({"claim_index": i, "grounded": False, "reason": "no_citation"})
            return result
        for cit in citations:
            check = check_citation(cit, fragments)
            check["claim_index"] = i
            result["citation_checks"].append(check)
            if not check["grounded"]:
                result["decision"] = "refuse"
                result["reason_code"] = REASON_UNSUPPORTED
                return result

    # 证据闭包：金标必达清单缺任何一项就拒答（多跳场景）
    required = case.get("gold", {}).get("required_fragment_ids", [])
    cited_ids = {c.get("fragment_id") for claim in claims for c in claim.get("citations", [])}
    missing = [rid for rid in required if rid not in cited_ids]
    if missing:
        result["closure_ok"] = False
        result["decision"] = "refuse"
        result["reason_code"] = REASON_COVERAGE
        result["missing_required"] = missing
        return result

    # 诊断口径：claim 文本逐字覆盖（不参与准入，仅输出信号）
    for claim in claims:
        norm_claim = normalize(claim.get("text", ""))
        union = normalize(" ".join(fragments[c["fragment_id"]]["text"] for c in claim.get("citations", []) if c["fragment_id"] in fragments))
        result["claim_verbatim_coverage"].append(bool(norm_claim) and norm_claim in union)

    return result


def _demo() -> None:
    """演示：对样例里两条坏答案逐条核验，打印拦截原因。"""
    fragments = load_fragments()
    cases = {c["id"]: c for c in _load_jsonl(DATA_DIR / "eval_cases.sample.jsonl")}
    answers = _load_jsonl(DATA_DIR / "answers.sample.jsonl")

    for rec in answers:
        if rec.get("result") != "answer":
            continue  # refused 形态在闸门①②就已拦下，直接透传
        verdict = verify_answer(rec["answer"], cases[rec["case_id"]], fragments)
        flag = "发布" if verdict["decision"] == "publish" else f"拒答({verdict['reason_code']})"
        print(f"[{rec['case_id']}] {flag}")
        if verdict["decision"] != "publish":
            for check in verdict["citation_checks"]:
                if not check["grounded"]:
                    print(f"    └─ 引用断裂：claim#{check.get('claim_index')} 指向 {check.get('fragment_id')}，{check.get('reason')}")
            if not verdict["closure_ok"]:
                print(f"    └─ 证据闭包缺失：{verdict.get('missing_required')}")
        diag = verdict["claim_verbatim_coverage"]
        if diag:
            print(f"    └─ claim 逐字覆盖(诊断口径)：{diag}")


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


if __name__ == "__main__":
    sys.exit(_demo())
