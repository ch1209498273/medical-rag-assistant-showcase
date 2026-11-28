#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""闸门⓪ 请求边界判定 · 脱敏参考实现。

在生成之前判断：这个问题该不该由机构知识助手回答。越界请求不进生成
链路，直接给固定原因码和转介话术。

为什么边界放在请求侧而不是答案侧：
- 「是否越界」是请求的属性。先让系统作答、再给答案贴一个安全标签，
  在临床场景等于已经说出了不该说的话。
- 生成后标记只能做事后审计，不能阻止内容产生。

判定用确定性短语规则，只做演示；生产系统由模型判官承担同一判断，
原因码与出口形态保持一致。

分类码与 verify_claims.py 的五个原因码并存，互不覆盖：
- CLINICAL_ADVICE_REQUEST  对具体患者的用药或方案给出建议
- CROSS_INSTITUTION_DATA   跨机构调取或比对患者信息
- ETHICAL_DECISION         治疗目标层面的伦理决策

只依赖标准库。样例全部为合成内容，不含真实药名与剂量组合。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

REASON_CLINICAL_ADVICE = "CLINICAL_ADVICE_REQUEST"
REASON_CROSS_INSTITUTION = "CROSS_INSTITUTION_DATA"
REASON_ETHICAL = "ETHICAL_DECISION"

BOUNDARY_REASON_CODES = (
    REASON_CLINICAL_ADVICE,
    REASON_CROSS_INSTITUTION,
    REASON_ETHICAL,
)

# 具体患者指代。必须是明确指向个体，不能是「透析中患者」这类泛指，
# 否则会误伤「透析中患者发生低血压应当如何处置」这类规程性问题。
_PATIENT_REFERENCE = (
    "该患者",
    "这位患者",
    "此患者",
    "本患者",
    "这个患者",
    "我的患者",
    "我的病人",
    "该病人",
)

# 个体化用药决策的表述，不含任何真实药名。
_MEDICATION_DECISION = (
    "用什么药",
    "怎么用药",
    "如何用药",
    "用药剂量",
    "剂量多少",
    "加量",
    "减量",
    "停药",
    "换药",
    "超说明书",
    "适应证外",
    "适应症外",
    "off-label",
    "能不能用",
    "该不该用",
)

# 个体化方案变更的表述。
_REGIMEN_CHANGE = (
    "改成",
    "改为",
    "加到",
    "减到",
    "换成",
    "调整为",
    "延长到",
    "缩短到",
)

# 跨机构标记：必须出现指向本机构之外的表述。
_CROSS_INSTITUTION_MARKER = (
    "外院",
    "外机构",
    "其他中心",
    "其它中心",
    "另一家",
    "别的中心",
    "其他机构",
    "跨中心",
    "跨机构",
    "两家中心",
    "两家机构",
    "不同中心",
)

# 被跨机构调取的数据对象。
_CROSS_INSTITUTION_DATA = (
    "患者名单",
    "患者信息",
    "患者资料",
    "病历",
    "档案",
    "化验结果",
    "依从性",
    "透析记录",
)

# 治疗目标层面的决策词。
_ETHICAL_MARKER = (
    "放弃治疗",
    "放弃透析",
    "停止透析",
    "终止透析",
    "撤治",
    "不再治疗",
    "不再透析",
    "安乐",
)

# 伦理决策需要伴随「该不该」这类征询，单说「停止透析的指征」属于规程问题。
_ETHICAL_ASK = (
    "要不要",
    "该不该",
    "是否应该",
    "是不是应该",
    "可以吗",
    "建议",
)

_TRANSFER_MESSAGE = {
    REASON_CLINICAL_ADVICE: (
        "该问题涉及对具体患者的用药或治疗方案调整，超出机构知识检索的范围。"
        "请由主管医师结合患者个体情况判断，必要时发起院内会诊。"
    ),
    REASON_CROSS_INSTITUTION: (
        "该问题涉及跨机构患者信息，超出本系统的数据边界。"
        "跨机构数据使用需经双方机构授权并履行相应审查程序。"
    ),
    REASON_ETHICAL: (
        "该问题涉及治疗目标层面的伦理决策，不宜由检索系统给出建议。"
        "建议由主管医师、患者家属与伦理委员会共同讨论后决定。"
    ),
}


def _hit(text: str, markers: tuple) -> bool:
    return any(marker in text for marker in markers)


def classify_request(question: str) -> Optional[str]:
    """返回边界分类码；未越界返回 None。

    判定顺序固定：伦理决策优先于个体化建议，因为「这位患者要不要放弃透析」
    同时含有患者指代与征询词，但它的处置出口是转介而非限域回答。
    """
    if not isinstance(question, str):
        return None
    text = "".join(question.split())

    if _hit(text, _ETHICAL_MARKER) and _hit(text, _ETHICAL_ASK):
        return REASON_ETHICAL

    if _hit(text, _CROSS_INSTITUTION_MARKER) and _hit(text, _CROSS_INSTITUTION_DATA):
        return REASON_CROSS_INSTITUTION

    if _hit(text, _PATIENT_REFERENCE) and (
        _hit(text, _MEDICATION_DECISION) or _hit(text, _REGIMEN_CHANGE)
    ):
        return REASON_CLINICAL_ADVICE

    return None


def boundary_refusal(question: str) -> Optional[Dict[str, Any]]:
    """越界请求的固定出口；未越界返回 None，交给后续闸门。"""
    reason_code = classify_request(question)
    if reason_code is None:
        return None
    return {
        "result": "refused",
        "reason_code": reason_code,
        "refusal": {"message": _TRANSFER_MESSAGE[reason_code]},
    }


def _demo() -> None:
    samples = (
        "这位患者透析中反复低血压，能不能把某种升压药超说明书加量使用，加多少合适？",
        "把外院患者的病历和我们中心的记录放在一起逐条比对，看谁的依从性更好。",
        "根据这些化验值，这位患者是不是已经属于透析不充分，直接改成每周四次？",
        "家里经济困难，这位患者要不要放弃透析、停止治疗？",
        "透析中患者发生低血压应当如何处置？",
    )
    for question in samples:
        verdict = boundary_refusal(question)
        label = verdict["reason_code"] if verdict else "未越界，进入后续闸门"
        print(f"[{label}] {question}")


if __name__ == "__main__":
    _demo()
