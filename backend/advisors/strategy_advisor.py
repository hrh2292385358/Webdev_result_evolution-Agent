"""StrategyAdvisor：基于分析结果生成自动评估策略建议。"""
from __future__ import annotations


class StrategyAdvisor:
    def __init__(self, task_id: str, aligned: list[dict], results: dict):
        self.task_id = task_id
        self.aligned = aligned
        self.results = results

    def generate(self) -> list[dict]:
        overall = self.results.get("overall", {})
        recs = []

        # 覆盖率低 → 建议检查 API 超时重试
        cov = overall.get("coverage", 1.0) or 1.0
        if cov < 0.8:
            recs.append(self._rec(
                problem="有效评分格覆盖率偏低",
                affected=["全部维度"],
                current="部分样本存在漏评",
                suggested="增加 API 调用重试机制（LLM_MAX_RETRIES），检查超时配置",
                priority="P1",
                time_cost="低", token_cost="低", complexity="低",
            ))

        # Bias 偏高 → 建议提示词校准
        bias = overall.get("bias", 0) or 0
        if abs(bias) > 0.3:
            direction = "偏乐观" if bias > 0 else "偏严格"
            recs.append(self._rec(
                problem=f"整体 Bias={bias:+.3f}（{direction}）",
                affected=["全部维度"],
                current="LLM评分存在系统性偏差",
                suggested=f"在 Skill Prompt 中增加校准指令，明确各分值的典型样本特征；考虑多Judge模型交叉验证",
                priority="P0" if abs(bias) > 0.5 else "P1",
                time_cost="中", token_cost="高", complexity="中",
            ))

        # 严重误判率高 → 建议增加确定性规则
        severe_rate = overall.get("severe_error_rate", 0) or 0
        if severe_rate > 0.05:
            recs.append(self._rec(
                problem=f"严重误判率 {severe_rate:.1%}（GT=0↔Auto=2）",
                affected=["高误判维度"],
                current="缺乏防止极端误判的确定性兜底规则",
                suggested="为 G 类（Gateway）维度增加确定性规则优先于 VLM 判断；添加截图质量检测前置过滤",
                priority="P0",
                time_cost="中", token_cost="低", complexity="中",
            ))

        # 通用建议
        recs.append(self._rec(
            problem="整体评估流程完整性",
            affected=["全部维度"],
            current="单次截图评估",
            suggested="建议增加交互前后对比截图（Hover/Click/Input/Submit），异步内容等待延时可配置",
            priority="P2",
            time_cost="高", token_cost="中", complexity="中",
        ))

        return recs

    def _rec(self, problem, affected, current, suggested, priority,
             time_cost, token_cost, complexity) -> dict:
        return {
            "rec_type": "strategy",
            "target_dimension": None,
            "category": None,
            "priority": priority,
            "status": "待验证",
            "llm_generated": False,
            "content": {
                "target_problem": problem,
                "affected_dimensions": affected,
                "current_strategy": current,
                "suggested_strategy": suggested,
                "time_cost": time_cost,
                "token_cost": token_cost,
                "implementation_complexity": complexity,
            },
        }
