"""WeightAdvisor：生成三套权重候选方案 A/B/C。"""
from __future__ import annotations

from pathlib import Path
import yaml

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"

DEFAULT_WEIGHTS = {
    "Functionality": 31, "Interactivity": 28,
    "Aesthetics": 31, "Content": 12,
}


def _load_current() -> dict:
    p = CONFIG_DIR / "weights.yaml"
    if p.exists():
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return {}


def _normalize(w: dict) -> dict:
    total = sum(w.values()) or 1
    return {k: round(v / total * 100, 2) for k, v in w.items()}


class WeightAdvisor:
    def __init__(self, task_id: str, results: dict, task_weights: dict = None):
        self.task_id = task_id
        self.results = results
        # 优先使用传入的任务级权重，其次读 config 文件
        if task_weights and task_weights.get("category_weights"):
            self.cfg = task_weights
        else:
            self.cfg = _load_current()
        self.current = self.cfg.get("category_weights", DEFAULT_WEIGHTS)

    def generate(self) -> list[dict]:
        return [
            self._scenario_a(),
            self._scenario_b(),
            self._scenario_c(),
        ]

    def _scenario_a(self) -> dict:
        """方案A：保守归一化——仅修复合计非100问题。"""
        norm = _normalize(self.current)
        changes = {k: round(norm[k] - self.current.get(k, 0), 2) for k in norm}
        return self._wrap("A", "保守归一化方案",
                          "将当前权重（合计非100）归一化至100，不改变相对比例",
                          self.current, norm, changes, recommended=True)

    def _scenario_b(self) -> dict:
        """方案B：业务平衡方案——功能和交互权重小幅上调，保持可解释性。"""
        adjusted = dict(self.current)
        adjusted["Functionality"]  = min(adjusted.get("Functionality",  31) + 2, 40)
        adjusted["Interactivity"]  = min(adjusted.get("Interactivity",  28) + 2, 40)
        adjusted["Aesthetics"]     = max(adjusted.get("Aesthetics",     31) - 2, 20)
        adjusted["Content"]        = max(adjusted.get("Content",        12) - 2, 5)
        norm = _normalize(adjusted)
        changes = {k: round(norm[k] - self.current.get(k, 0), 2) for k in norm}
        return self._wrap("B", "业务平衡方案",
                          "适度上调核心功能和交互权重，小幅下调美观和内容权重，保持业务可解释性",
                          self.current, norm, changes)

    def _scenario_c(self) -> dict:
        """方案C：数据驱动——差异越大（一致率越低）的类别需要更高关注权重。"""
        by_cat = self.results.get("by_category", {})
        base = {}
        for cat in self.current:
            m = by_cat.get(cat, {})
            exact = m.get("exact_match")
            if exact is None:
                # 无数据的类别用当前权重保持不变
                base[cat] = self.current.get(cat, 0)
            else:
                # 一致率越低 → 差异越大 → 权重越高（需要更多关注/优化资源）
                base[cat] = max(1 - exact, 0.05)

        total = sum(base.values()) or 1
        data_driven = {k: round(v / total * 100, 2) for k, v in base.items()}
        changes = {k: round(data_driven.get(k, 0) - self.current.get(k, 0), 2)
                   for k in self.current}
        return self._wrap("C", "数据驱动方案",
                          "按各类别精确一致率的反向指标调整权重——自动评估与人工差异越大的类别"
                          "获得更高权重（代表该类别更需要优先校准）。"
                          "注意：此方案不能替代业务决策，仅供参考",
                          self.current, data_driven, changes)

    def _wrap(self, name, title, desc, current, suggested, changes, recommended=False) -> dict:
        return {
            "rec_type": "weight",
            "target_dimension": None,
            "category": None,
            "priority": "P1",
            "status": "待验证",
            "llm_generated": False,
            "content": {
                "scenario_name": f"方案{name}：{title}",
                "description": desc,
                "current_weights": current,
                "suggested_weights": suggested,
                "changes": changes,
                "normalized": True,
                "recommended": recommended,
            },
        }
