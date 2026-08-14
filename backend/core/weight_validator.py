"""WeightValidator：检查权重配置的合法性。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def load_weights_cfg() -> dict:
    p = CONFIG_DIR / "weights.yaml"
    if p.exists():
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return {}


class WeightValidator:
    def __init__(self, cfg: Optional[dict] = None):
        self.cfg = cfg or load_weights_cfg()

    def validate(self) -> dict:
        """
        返回 {status: pass|warn|fail, issues: [{level, message}]}
        """
        issues = []
        cfg = self.cfg
        cat_weights: dict = cfg.get("category_weights", {})
        categories: dict  = cfg.get("categories", {})
        gateway: list     = cfg.get("gateway", [])
        eq_within: bool   = cfg.get("equal_within_category", True)
        dim_weights: dict = cfg.get("dimension_weights", {})

        # 1. 权重合计检查
        total = sum(cat_weights.values()) if cat_weights else 0
        if total == 0:
            issues.append({"level":"warn","message":"未找到类别权重配置，将使用等权分配"})
        elif abs(total - 100) > 0.01:
            issues.append({"level":"warn",
                "message":f"类别权重合计为 {total}（非100），分析时将自动归一化"})

        # 2. DataPersistence 检查
        if "DataPersistence" in categories and "DataPersistence" not in cat_weights:
            issues.append({"level":"warn",
                "message":"DataPersistence 维度已定义但缺少类别权重，建议配置或标记为 disabled"})

        # 3. 负权重
        for cat, w in cat_weights.items():
            if w < 0:
                issues.append({"level":"error","message":f"类别 {cat} 权重为负值（{w}），不合法"})

        # 4. 启用类别至少要有一个维度
        for cat, members in categories.items():
            if cat in cat_weights and cat_weights[cat] > 0 and not members:
                issues.append({"level":"error","message":f"类别 {cat} 权重>0 但没有配置维度"})

        # 5. 维度重复归属
        seen_dims: dict[str, str] = {}
        for cat, members in categories.items():
            for d in members:
                if d in seen_dims:
                    issues.append({"level":"error",
                        "message":f"维度 {d} 同时属于 {seen_dims[d]} 和 {cat}"})
                seen_dims[d] = cat

        # 6. equal_within_category=false 时需要具体维度权重
        if not eq_within and not dim_weights:
            issues.append({"level":"warn",
                "message":"equal_within_category=false 但未配置具体维度权重，将退回等权分配"})

        has_error = any(i["level"]=="error" for i in issues)
        status = "fail" if has_error else ("warn" if issues else "pass")
        return {"status": status, "issues": issues, "weight_sum": total}
