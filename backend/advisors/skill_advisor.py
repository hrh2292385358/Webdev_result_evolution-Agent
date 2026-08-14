"""SkillAdvisor：基于指标生成 Skill 优化候选建议。"""
from __future__ import annotations

from collections import defaultdict


class SkillAdvisor:
    def __init__(self, task_id: str, aligned: list[dict], results: dict,
                 dim_info: dict[str, dict] = None):
        self.task_id  = task_id
        self.aligned  = aligned
        self.results  = results
        # dim_info: {code: {rubric_points, exemption, scale, name}}
        # 兼容旧式 {code: str}（直接传 rubric 字符串）
        raw = dim_info or {}
        if raw and isinstance(next(iter(raw.values())), str):
            self.dim_info = {code: {"rubric_points": v, "exemption": "", "scale": "", "name": ""}
                             for code, v in raw.items()}
        else:
            self.dim_info = raw

    def _info(self, code: str) -> dict:
        return self.dim_info.get(code) or {}

    def generate(self) -> list[dict]:
        by_dim = self.results.get("by_dimension", {})
        recs = []
        for code, m in by_dim.items():
            exact = m.get("exact_match")
            if exact is None or exact >= 0.7:
                continue

            bias = m.get("bias", 0) or 0
            mae  = m.get("mae", 0) or 0

            if bias > 0.3:
                direction = "偏高（自动评分系统性偏乐观）"
                priority  = "P0" if bias > 0.6 else "P1"
            elif bias < -0.3:
                direction = "偏低（自动评分系统性偏严格）"
                priority  = "P0" if bias < -0.6 else "P1"
            else:
                direction = "随机误差为主"
                priority  = "P2"

            severe_samples = [
                r for r in self.aligned
                if r.get("dimension_code") == code
                and r.get("delta") is not None
                and abs(r.get("delta", 0)) == 2
            ][:3]

            info     = self._info(code)
            rubric   = (info.get("rubric_points") or "").strip()
            exemption = (info.get("exemption") or "").strip()
            scale    = (info.get("scale") or "").strip()
            name     = (info.get("name") or code).strip()

            # 建议文字：针对偏差方向，不含评分标准摘要
            suggestion = (
                f"建议对照 {code}（{name}）的评分标准重新校准评分边界，"
                f"重点关注{direction}场景。"
                f"当前 Bias={bias:+.3f}，MAE={mae:.3f}，建议逐条核查评分标准中各档判定条件，"
                f"并通过增加正反例样本标注来收窄评分人分歧。"
            )

            # 生成优化后的完整新评分标准
            suggested_rubric = _build_suggested_rubric(
                code, name, scale, rubric, exemption, bias, mae
            )

            recs.append({
                "rec_type": "skill",
                "target_dimension": code,
                "category": None,
                "priority": priority,
                "status": "待验证",
                "llm_generated": False,
                "content": {
                    "current_problem":    f"维度 {code} 精确一致率 {exact:.1%}，Bias={bias:+.3f}，MAE={mae:.3f}",
                    "error_direction":    direction,
                    "suggestion":         suggestion,
                    "suggested_rubric":   suggested_rubric,
                    "supporting_samples": len([r for r in self.aligned
                                               if r.get("dimension_code") == code
                                               and r.get("delta") is not None]),
                    "severe_sample_count": len(severe_samples),
                    "metrics": {"exact_match": exact, "bias": bias, "mae": mae},
                },
            })

        return recs


def _build_suggested_rubric(code: str, name: str, scale: str,
                             rubric: str, exemption: str,
                             bias: float, mae: float) -> str:
    """
    在原有 rubric 基础上，根据偏差方向追加校准提示，构成完整新评分标准建议。
    """
    lines = []
    lines.append(f"## {code} · {name}")
    if scale:
        lines.append(f"量表：{scale}")
    lines.append("")

    if rubric:
        lines.append("### 评分标准（原始）")
        lines.append(rubric.rstrip())
        lines.append("")

    # 校准建议段
    lines.append("### 校准建议（基于本次数据分析）")
    if bias > 0.3:
        lines.append(
            f"- 当前自动评分整体偏乐观（Bias={bias:+.3f}），"
            "建议将各档判定条件向严格方向收紧："
        )
        lines.append("  - 检查高分档（最高分）的判定条件是否过于宽松，增加必须同时满足的细项要求")
        lines.append("  - 补充至少2个「给高分但实际应给中/低分」的反例样本")
    elif bias < -0.3:
        lines.append(
            f"- 当前自动评分整体偏严格（Bias={bias:+.3f}），"
            "建议将各档判定条件向宽松方向调整："
        )
        lines.append("  - 检查低分档的判定条件是否过于苛刻，放宽边缘情况的判定")
        lines.append("  - 补充至少2个「给低分但实际应给中/高分」的反例样本")
    else:
        lines.append(
            f"- 当前误差以随机波动为主（MAE={mae:.3f}），"
            "建议重点补充评分边界处（1分档）的典型案例："
        )
        lines.append("  - 明确区分「1分」与「0分」、「1分」与「2分」的核心判断依据")
        lines.append("  - 增加各档正例3条、反例2条以减少歧义")

    if mae > 0.5:
        lines.append(f"- MAE={mae:.3f} 偏高，建议对该维度进行评分人一致性测试（IRR），")
        lines.append("  确认标准定义本身是否清晰，必要时重写评分标准")

    lines.append("")

    if exemption:
        lines.append("### 豁免条件")
        lines.append(exemption.rstrip())

    return "\n".join(lines)
