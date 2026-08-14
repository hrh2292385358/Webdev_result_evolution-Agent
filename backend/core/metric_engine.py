"""MetricEngine：所有确定性评估指标计算。LLM 不参与任何指标计算。"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional


def _valid(r: dict) -> bool:
    """有效评分格：GT和Auto均有合法分值，且均通过is_valid检查。"""
    return (r.get("gt_is_valid") and r.get("auto_is_valid")
            and r.get("ground_truth_score") is not None
            and r.get("auto_score") is not None
            and not r.get("gt_is_exempt") and not r.get("auto_is_exempt"))


class MetricEngine:
    """
    输入 aligned_records（DataAligner.align() 的结果），
    计算整体/分类/维度/模型各层级的指标。
    """

    def __init__(self, aligned: list[dict], score_range: list[int] = None,
                 dim_to_category: dict[str, str] = None):
        self.aligned = aligned
        self.score_range = score_range or [0, 1, 2]
        self.dim_to_cat = dim_to_category or {}

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    def compute_all(self) -> dict:
        valid = [r for r in self.aligned if _valid(r)]
        theoretical = len(self.aligned)

        overall = self._metrics(valid, theoretical, all_records=self.aligned)
        by_cat  = self._group_metrics_with_all(lambda r: self.dim_to_cat.get(r["dimension_code"], "Unknown"))
        by_dim  = self._group_metrics_with_all(lambda r: r["dimension_code"])
        by_model = self._group_metrics_with_all(lambda r: r.get("candidate_model") or "Unknown")

        # 5 类数据质量统计
        matched         = sum(1 for r in self.aligned if r.get("has_auto"))
        gt_only         = sum(1 for r in self.aligned if not r.get("has_auto"))
        missing_auto    = sum(1 for r in self.aligned
                              if r.get("has_auto") and r.get("auto_score") is None
                              and not r.get("auto_is_exempt"))
        illegal_scores  = sum(1 for r in self.aligned
                              if (r.get("gt_is_valid") is False and not r.get("gt_is_exempt"))
                              or (r.get("auto_is_valid") is False and not r.get("auto_is_exempt")
                                  and r.get("has_auto") and r.get("auto_score") is not None))
        exempt_cells    = sum(1 for r in self.aligned
                              if r.get("gt_is_exempt") or r.get("auto_is_exempt"))

        data_quality = {
            "matched_cells":      matched,
            "gt_only_cells":      gt_only,
            "auto_only_cells":    0,   # 由 DataAligner 统计后注入
            "missing_auto_cells": missing_auto,
            "illegal_score_cells": illegal_scores,
            "exempt_cells":       exempt_cells,
        }

        overall["data_quality"] = data_quality

        # 模型空数据告警
        model_warnings = self._model_warnings()

        return {
            "overall":       overall,
            "by_category":   by_cat,
            "by_dimension":  by_dim,
            "by_model":      by_model,
            "model_warnings": model_warnings,
        }

    # ------------------------------------------------------------------
    # 单组指标
    # ------------------------------------------------------------------
    def _metrics(self, records: list[dict], theoretical: int = None,
                 all_records: list[dict] = None) -> dict:
        """
        records: 有效评分格（双方均合法）
        all_records: 该分组全部对齐记录（含空/豁免），用于统计无效格
        """
        n = len(records)
        all_n = len(all_records) if all_records is not None else (theoretical or n)

        # 无效格统计（基于 all_records）
        if all_records is not None:
            empty_gt   = sum(1 for r in all_records if r.get("ground_truth_score") is None and not r.get("gt_is_exempt"))
            empty_auto = sum(1 for r in all_records if r.get("auto_score") is None and not r.get("auto_is_exempt") and r.get("has_auto"))
            exempt     = sum(1 for r in all_records if r.get("gt_is_exempt") or r.get("auto_is_exempt"))
            invalid_cells = all_n - n
            valid_rate = round(n / all_n, 4) if all_n > 0 else 0.0
        else:
            empty_gt = empty_auto = exempt = invalid_cells = 0
            valid_rate = 1.0

        if n == 0:
            return {
                "valid_cells": 0, "invalid_cells": invalid_cells,
                "empty_gt_cells": empty_gt, "empty_auto_cells": empty_auto,
                "exempt_cells": exempt, "valid_rate": valid_rate,
                "theoretical_cells": theoretical or 0,
                "coverage": 0.0, "exact_match": None,
                "within1": None, "mae": None, "bias": None,
                "confusion_matrix": {}, "precision_recall_f1": {},
                "macro_f1": None, "weighted_f1": None,
                "severe_error_rate": None,
                "gt_distribution": {}, "auto_distribution": {},
            }

        gt_vals   = [r["ground_truth_score"] for r in records]
        auto_vals = [r["auto_score"] for r in records]
        deltas    = [a - g for g, a in zip(gt_vals, auto_vals)]

        exact_match = sum(1 for g, a in zip(gt_vals, auto_vals) if g == a) / n
        within1     = sum(1 for d in deltas if abs(d) <= 1) / n
        mae         = sum(abs(d) for d in deltas) / n
        bias        = sum(deltas) / n

        severe = sum(1 for g, a in zip(gt_vals, auto_vals)
                     if (g == 0 and a == 2) or (g == 2 and a == 0))
        severe_rate = severe / n

        cm = self._confusion_matrix(gt_vals, auto_vals)
        prf = self._precision_recall_f1(cm)

        coverage = n / (theoretical or n)

        gt_dist   = self._distribution(gt_vals)
        auto_dist = self._distribution(auto_vals)

        return {
            "valid_cells":        n,
            "invalid_cells":      invalid_cells,
            "empty_gt_cells":     empty_gt,
            "empty_auto_cells":   empty_auto,
            "exempt_cells":       exempt,
            "valid_rate":         valid_rate,
            "exact_match_num":    sum(1 for g, a in zip(gt_vals, auto_vals) if g == a),
            "theoretical_cells":  theoretical or n,
            "coverage":           round(coverage, 4),
            "exact_match":        round(exact_match, 4),
            "within1":            round(within1, 4),
            "mae":                round(mae, 4),
            "bias":               round(bias, 4),
            "severe_errors":      severe,
            "severe_error_rate":  round(severe_rate, 4),
            "confusion_matrix":   cm,
            "precision_recall_f1": prf,
            "macro_f1":           round(prf.get("macro_f1", 0), 4),
            "weighted_f1":        round(prf.get("weighted_f1", 0), 4),
            "gt_distribution":    gt_dist,
            "auto_distribution":  auto_dist,
        }

    def _group_metrics_with_all(self, key_fn) -> dict[str, dict]:
        """按 key_fn 分组，将全部记录和有效记录分别传入 _metrics。"""
        all_groups: dict[str, list[dict]] = defaultdict(list)
        valid_groups: dict[str, list[dict]] = defaultdict(list)
        for r in self.aligned:
            k = key_fn(r)
            all_groups[k].append(r)
            if _valid(r):
                valid_groups[k].append(r)
        return {k: self._metrics(valid_groups.get(k, []), len(all_groups[k]), all_groups[k])
                for k in all_groups}

    def _group_metrics(self, records: list[dict], key_fn) -> dict[str, dict]:
        groups: dict[str, list[dict]] = defaultdict(list)
        for r in records:
            groups[key_fn(r)].append(r)
        return {k: self._metrics(v) for k, v in groups.items()}

    def _model_warnings(self) -> list[dict]:
        """对每个模型检测空数据，生成告警及可能性建议。"""
        from collections import defaultdict
        model_all: dict[str, list[dict]] = defaultdict(list)
        for r in self.aligned:
            m = r.get("candidate_model") or "Unknown"
            model_all[m].append(r)

        warnings = []
        for model, recs in sorted(model_all.items()):
            total = len(recs)
            empty_auto = sum(1 for r in recs
                             if r.get("auto_score") is None and not r.get("auto_is_exempt"))
            empty_gt   = sum(1 for r in recs
                             if r.get("ground_truth_score") is None and not r.get("gt_is_exempt"))
            exempt     = sum(1 for r in recs if r.get("gt_is_exempt") or r.get("auto_is_exempt"))
            valid      = sum(1 for r in recs if _valid(r))

            issues = []
            suggestions = []

            if empty_auto > 0:
                # 判断是否因 G1=0 触发的流水线跳过
                g1_auto_zero = any(r.get("dimension_code") == "G1"
                                   and r.get("auto_score") == 0 for r in recs)
                if g1_auto_zero and empty_auto > 5:
                    issues.append(f"AutoEval 空数据格 {empty_auto} 个")
                    suggestions.append("G1=0（部署失败），AutoEval 流水线未评后续维度，属正常行为")
                else:
                    issues.append(f"AutoEval 空数据格 {empty_auto} 个")
                    suggestions.append("可能原因：AutoEval 流水线漏评、API 超时或网络异常，建议核查日志")

            if empty_gt > 0:
                # 判断 GT 空值是否因 G1=0 后人工不填
                g1_gt_zero = any(r.get("dimension_code") == "G1"
                                 and r.get("ground_truth_score") == 0 for r in recs)
                if g1_gt_zero and empty_gt > 5:
                    issues.append(f"GT 空数据格 {empty_gt} 个")
                    suggestions.append("G1=0，人工标注未填写后续维度，属正常行为")
                else:
                    issues.append(f"GT 空数据格 {empty_gt} 个")
                    suggestions.append("可能原因：人工标注漏填，建议核查 GT 文件")

            if issues:
                warnings.append({
                    "model":        model,
                    "total_cells":  total,
                    "valid_cells":  valid,
                    "invalid_cells": total - valid,
                    "empty_auto_cells": empty_auto,
                    "empty_gt_cells":   empty_gt,
                    "exempt_cells":     exempt,
                    "valid_rate":   round(valid / total, 4) if total > 0 else 0.0,
                    "issues":       issues,
                    "suggestions":  suggestions,
                })

        return warnings
    def _confusion_matrix(self, gt: list, auto: list) -> dict:
        labels = sorted(set(self.score_range))
        cm: dict[str, dict[str, int]] = {str(l): {str(l2): 0 for l2 in labels} for l in labels}
        for g, a in zip(gt, auto):
            sg, sa = str(int(g)), str(int(a))
            if sg in cm and sa in cm[sg]:
                cm[sg][sa] += 1
        return cm

    # ------------------------------------------------------------------
    # Precision / Recall / F1（多分类，非Micro）
    # ------------------------------------------------------------------
    def _precision_recall_f1(self, cm: dict) -> dict:
        labels = sorted(cm.keys())
        prf: dict[str, dict] = {}
        support_total = sum(sum(cm[l].values()) for l in labels)

        for label in labels:
            tp = cm[label].get(label, 0)
            fp = sum(cm[other].get(label, 0) for other in labels if other != label)
            fn = sum(cm[label].get(other, 0) for other in labels if other != label)
            prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            rec  = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1   = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
            support = sum(cm[label].values())
            prf[label] = {"precision": round(prec,4), "recall": round(rec,4),
                          "f1": round(f1,4), "support": support}

        macro_p  = sum(v["precision"] for v in prf.values()) / len(labels) if labels else 0
        macro_r  = sum(v["recall"] for v in prf.values()) / len(labels) if labels else 0
        macro_f1 = sum(v["f1"] for v in prf.values()) / len(labels) if labels else 0

        weighted_f1 = (sum(v["f1"] * v["support"] for v in prf.values()) / support_total
                       if support_total > 0 else 0)

        return {
            **prf,
            "macro_precision": round(macro_p, 4),
            "macro_recall":    round(macro_r, 4),
            "macro_f1":        round(macro_f1, 4),
            "weighted_f1":     round(weighted_f1, 4),
        }

    # ------------------------------------------------------------------
    # 分布统计
    # ------------------------------------------------------------------
    def _distribution(self, vals: list) -> dict:
        dist: dict[str, int] = {str(s): 0 for s in self.score_range}
        for v in vals:
            k = str(int(v))
            if k in dist:
                dist[k] += 1
        return dist

    # ------------------------------------------------------------------
    # Fail 指标（GT=0 为 Fail，GT>0 为 Non-fail）
    # ------------------------------------------------------------------
    def fail_metrics(self, records: list[dict] = None,
                     fail_threshold: float = 0) -> dict:
        """计算 Fail Precision / Recall / F1 及误报/漏报数量。"""
        recs = [r for r in (records or self.aligned) if _valid(r)]
        if not recs:
            return {}

        gt_fail   = [1 if r["ground_truth_score"] <= fail_threshold else 0 for r in recs]
        auto_fail = [1 if r["auto_score"] <= fail_threshold else 0 for r in recs]

        tp = sum(1 for g, a in zip(gt_fail, auto_fail) if g == 1 and a == 1)
        fp = sum(1 for g, a in zip(gt_fail, auto_fail) if g == 0 and a == 1)  # 误报
        fn = sum(1 for g, a in zip(gt_fail, auto_fail) if g == 1 and a == 0)  # 漏报

        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec  = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1   = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0

        return {
            "fail_precision": round(prec, 4),
            "fail_recall":    round(rec, 4),
            "fail_f1":        round(f1, 4),
            "false_fail_count":  fp,
            "missed_fail_count": fn,
        }
