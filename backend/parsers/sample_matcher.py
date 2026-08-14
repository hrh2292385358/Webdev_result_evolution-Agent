"""SampleMatcher：按多级 key 对齐 GT 和 AutoEval 的行记录。"""
from __future__ import annotations

import re
from typing import Any, Optional


# 样本 ID 字段候选名（按优先级）
ID_FIELD_CANDIDATES = [
    ["task_id"],
    ["data_id"],
    ["query_id"],
    ["website_id"],
    ["query"],
    ["response", "bridge_url", "bridge_URL"],
]

MODEL_FIELD_CANDIDATES = ["candidate_model", "model", "model_id"]


def _norm_text(s: Any) -> str:
    if s is None:
        return ""
    return re.sub(r"\s+", " ", str(s).strip().lower())


def _pick(row: dict, candidates: list[str]) -> Optional[str]:
    """从 row 中按候选名列表取第一个非空值。"""
    for c in candidates:
        v = row.get(c)
        if v is not None and str(v).strip():
            return str(v).strip()
    return None


def _build_key(row: dict, level: int) -> Optional[str]:
    """
    level 0：data_id + query_id + candidate_model（最稳定）
    level 1：data_id + candidate_model
    level 2：query文本 + candidate_model
    level 3：response / bridge_url
    """
    model = _pick(row, MODEL_FIELD_CANDIDATES) or ""
    if level == 0:
        did   = _pick(row, ["data_id"]) or ""
        qid   = _pick(row, ["query_id"]) or ""
        if did or qid:
            return f"{did}||{qid}||{model}"
    elif level == 1:
        did = _pick(row, ["data_id"]) or ""
        if did:
            return f"{did}||{model}"
    elif level == 2:
        q = _norm_text(_pick(row, ["query"]))
        if q:
            return f"q:{q[:80]}||{model}"
    elif level == 3:
        url = _pick(row, ["response","bridge_url","bridge_URL"]) or ""
        if url:
            return f"url:{url}"
    return None


class SampleMatcher:
    def __init__(self, gt_rows: list[dict], auto_rows: list[dict]):
        self.gt_rows   = gt_rows
        self.auto_rows = auto_rows

    def match(self) -> dict:
        """
        多级降级匹配，返回：
        {
          matched:      [(gt_row, auto_row), ...],
          gt_only:      [gt_row, ...],
          auto_only:    [auto_row, ...],
          duplicates:   [row, ...],
          match_level:  int,  # 使用的匹配级别
          issues:       [{level, message}, ...]
        }
        """
        for level in range(4):
            result = self._try_match(level)
            if result["matched"] or (not result["gt_only"] and not result["auto_only"]):
                result["match_level"] = level
                return result

        # 兜底：全部 GT 和 Auto 都无法匹配
        return {
            "matched": [], "gt_only": self.gt_rows, "auto_only": self.auto_rows,
            "duplicates": [], "match_level": -1,
            "issues": [{"level":"error","message":"无法自动对齐样本，请检查 ID 字段是否一致"}],
        }

    def _try_match(self, level: int) -> dict:
        auto_index: dict[str, list[dict]] = {}
        for r in self.auto_rows:
            k = _build_key(r, level)
            if k:
                auto_index.setdefault(k, []).append(r)

        matched, gt_only, duplicates = [], [], []
        used_auto_keys: set[str] = set()

        for gr in self.gt_rows:
            k = _build_key(gr, level)
            if k is None:
                gt_only.append(gr)
                continue
            hits = auto_index.get(k, [])
            if not hits:
                gt_only.append(gr)
            elif len(hits) == 1:
                matched.append((gr, hits[0]))
                used_auto_keys.add(k)
            else:
                # 多条 auto 命中同一 key → 重复
                duplicates.extend(hits)
                matched.append((gr, hits[0]))
                used_auto_keys.add(k)

        auto_only = [r for r in self.auto_rows
                     if _build_key(r, level) not in used_auto_keys]

        issues = []
        if len(gt_only) > 0:
            issues.append({"level":"warn","message":f"GT中有 {len(gt_only)} 个样本在AutoEval中找不到对应行"})
        if len(auto_only) > 0:
            issues.append({"level":"warn","message":f"AutoEval中有 {len(auto_only)} 个多余样本"})
        if duplicates:
            issues.append({"level":"warn","message":f"发现 {len(duplicates)} 条重复行"})
        if len(gt_only) > len(self.gt_rows) * 0.3:
            issues.append({"level":"error","message":"超过30%的GT样本无法匹配，请检查ID字段或文件内容"})

        return {
            "matched": matched, "gt_only": gt_only,
            "auto_only": auto_only, "duplicates": duplicates,
            "issues": issues,
        }

    @property
    def stats(self) -> dict:
        r = self.match()
        return {
            "matched": len(r["matched"]),
            "gt_only": len(r["gt_only"]),
            "auto_only": len(r["auto_only"]),
            "duplicates": len(r["duplicates"]),
            "match_level": r["match_level"],
            "issues": r["issues"],
        }
