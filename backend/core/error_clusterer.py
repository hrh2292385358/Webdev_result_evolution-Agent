"""ErrorClusterer：规则归因 + 可选 LLM 总结。"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional


ROOT_CAUSE_CATEGORIES = [
    "数据或对齐问题",
    "Ground Truth异常或争议风险",
    "Evidence采集不足",
    "浏览器交互覆盖不足",
    "Skill定义或评分边界不清",
    "确定性规则过严",
    "确定性规则过松",
    "VLM Prompt问题",
    "Scorer或聚合策略问题",
    "Judge模型偏高",
    "Judge模型偏低",
    "Judge模型稳定性问题",
    "API失败、超时或漏评",
    "无法确定，需要进一步验证",
]


class ErrorClusterer:
    """
    使用确定性规则对差异记录进行初步归因，
    可选调用 LLM 对每个维度生成更清晰的文字总结。
    """

    def __init__(self, aligned: list[dict], results: dict, use_llm: bool = True,
                 judge_model: str = "", dim_rubrics: dict[str, str] = None):
        self.aligned = aligned
        self.results = results
        self.use_llm = use_llm
        self.judge_model = judge_model
        self.dim_rubrics = dim_rubrics or {}

    def cluster(self) -> dict[str, list[dict]]:
        """返回 {dimension_code: [归因记录, ...]}"""
        by_dim: dict[str, list[dict]] = defaultdict(list)
        for r in self.aligned:
            if r.get("delta") is None:
                continue
            code = r.get("dimension_code", "")
            cause = self._rule_classify(r)
            by_dim[code].append({**r, "root_cause_category": cause})
        return dict(by_dim)

    def _rule_classify(self, r: dict) -> str:
        delta = r.get("delta", 0) or 0
        gt    = r.get("ground_truth_score")
        auto  = r.get("auto_score")

        # 极端翻转
        if gt == 0 and auto == 2:
            return "Skill定义或评分边界不清"
        if gt == 2 and auto == 0:
            return "Skill定义或评分边界不清"

        # 系统性偏高/偏低
        dim_metrics = self.results.get("by_dimension", {}).get(
            r.get("dimension_code", ""), {})
        bias = dim_metrics.get("bias", 0) or 0
        if delta > 0 and bias > 0.3:
            return "Judge模型偏高"
        if delta < 0 and bias < -0.3:
            return "Judge模型偏低"

        # Auto 无评分
        if auto is None:
            return "API失败、超时或漏评"

        # 小偏差
        if abs(delta) == 1:
            return "Skill定义或评分边界不清"

        return "无法确定，需要进一步验证"

    def enrich_with_llm(self, dim_clusters: dict[str, list[dict]]) -> dict[str, str]:
        """
        对问题突出的维度调用 LLM 生成文字总结。
        返回 {dimension_code: llm_summary}；LLM 不可用时返回空 {}。
        """
        from ..llm.gateway_client import LLMGatewayClient
        judge_model = getattr(self, "judge_model", "")
        client = LLMGatewayClient(judge_model=judge_model)
        if not client.available:
            return {}

        summaries = {}
        by_dim_metrics = self.results.get("by_dimension", {})

        for code, records in dim_clusters.items():
            m = by_dim_metrics.get(code, {})
            exact = m.get("exact_match", 1.0)
            if exact is None or exact >= 0.7:
                continue  # 只对问题维度调用 LLM

            samples_txt = "\n".join(
                f"- GT={r.get('ground_truth_score')} Auto={r.get('auto_score')} "
                f"delta={r.get('delta')} reason={str(r.get('auto_reason',''))[:80]}"
                for r in records[:5]
            )
            rubric_txt = (self.dim_rubrics.get(code, "") or "").strip()
            rubric_section = f"\n该维度评分标准：\n{rubric_txt[:300]}\n" if rubric_txt else ""
            prompt = (
                f"你是一名自动化评估系统分析专家。\n"
                f"维度：{code}\n"
                f"精确一致率：{exact:.1%}，Bias={m.get('bias',0):+.3f}，MAE={m.get('mae',0):.3f}\n"
                f"{rubric_section}"
                f"代表性错误样本（最多5条）：\n{samples_txt}\n\n"
                f"请结合上方评分标准，用中文简洁总结该维度的主要问题和根本原因（100字以内），"
                f"并以 JSON 格式返回：{{\"summary\": \"...\", \"root_cause\": \"...\"}}"
            )
            result = client.chat_json(prompt, schema_keys=["summary", "root_cause"])
            if result:
                summaries[code] = result.get("summary", "")
            else:
                summaries[code] = "LLM建议生成失败，请查看基础指标"

        return summaries
