#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评测 runner · 脱敏参考实现。

按 README 第 08 节口径，对 12 题合成样例计算：
- 回答率（可答题中被发布回答的比例）
- 无答案拒答率
- 引用有效率（逐字诊断口径）
- 值匹配正确率（准入口径：金标关键值出现在答案文本中）
- 内容错误答案发布次数（应为 0）

确定性输出：同样的输入永远给同样的结果。零依赖，Python 3.8+。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from verify_claims import REASON_OUT_OF_SCOPE, load_fragments, normalize, verify_answer

DATA_DIR = Path(__file__).parent / "data"
REPORT_PATH = Path(__file__).parent / "report.json"


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def run_eval() -> Dict[str, Any]:
    fragments = load_fragments()
    cases = {c["id"]: c for c in _load_jsonl(DATA_DIR / "eval_cases.sample.jsonl")}
    answers = _load_jsonl(DATA_DIR / "answers.sample.jsonl")

    answerable = {cid: c for cid, c in cases.items() if c["kind"] == "answerable"}
    no_answer = {cid: c for cid, c in cases.items() if c["kind"] == "no_answer"}

    published: List[Dict[str, Any]] = []
    refused: List[Dict[str, Any]] = []
    total_citations = 0
    grounded_citations = 0
    value_match_hits = 0
    wrong_published = 0
    missing_cases: List[str] = []

    answered_ids = {rec["case_id"] for rec in answers}
    missing_cases = sorted(set(cases) - answered_ids)

    for rec in answers:
        case = cases[rec["case_id"]]
        if rec.get("result") == "refused":
            refused.append({"case_id": rec["case_id"], "reason_code": rec.get("reason_code")})
            continue
        verdict = verify_answer(rec["answer"], case, fragments)
        if verdict["decision"] != "publish":
            refused.append({"case_id": rec["case_id"], "reason_code": verdict["reason_code"]})
            continue

        ans_text = "".join(claim.get("text", "") for claim in rec["answer"].get("claims", []))
        gold_values = case.get("gold", {}).get("key_values", [])
        value_ok = all(normalize(v) in normalize(ans_text) for v in gold_values)
        if not value_ok:
            # 值不匹配仍然发布 = 内容错误答案发布
            wrong_published += 1
        else:
            value_match_hits += 1
        published.append({"case_id": rec["case_id"], "value_match": value_ok})

        for claim in rec["answer"].get("claims", []):
            for cit in claim.get("citations", []):
                total_citations += 1
                frag = fragments.get(cit.get("fragment_id", ""))
                if frag and normalize(cit.get("quote", "")) in normalize(frag["text"]):
                    grounded_citations += 1

    n_ans, n_no = len(answerable), len(no_answer)
    report = {
        "note": "脱敏参考实现的演示指标，基于合成样例，不代表生产系统评测结果",
        "sample_size": {"answerable": n_ans, "no_answer": n_no},
        "answer_rate_published": f"{len(published)}/{n_ans}",
        "no_answer_refusal_rate": f"{sum(1 for r in refused if r['case_id'] in no_answer)}/{n_no}",
        "citation_grounding_rate": f"{grounded_citations}/{total_citations}",
        "value_match_admission": f"{value_match_hits}/{len(published) + wrong_published}",
        "wrong_answer_published": wrong_published,
        "refused_detail": refused,
        "missing_answers_for_cases": missing_cases,
    }
    return report


def main() -> None:
    report = run_eval()
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 56)
    print("评测样例结果（合成数据 · 参考实现演示）")
    print("=" * 56)
    print(f"可答题发布回答        {report['answer_rate_published']}")
    print(f"无答案题拒答          {report['no_answer_refusal_rate']}")
    print(f"引用逐字命中          {report['citation_grounding_rate']}")
    print(f"值匹配准入            {report['value_match_admission']}")
    print(f"内容错误答案发布      {report['wrong_answer_published']} 次")
    print("-" * 56)
    for r in report["refused_detail"]:
        print(f"  拒答 {r['case_id']:<8} 固定原因码: {r['reason_code']}")
    print(f"\n明细已写入 {REPORT_PATH.name}")


if __name__ == "__main__":
    main()
