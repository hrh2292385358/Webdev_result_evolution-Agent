"""SchemaDetector：识别Excel表头中的样本ID字段和评分维度字段。"""
from __future__ import annotations

import re
from typing import Optional

# 样本字段候选（逻辑名 -> 可能的列名列表）
# 注意：candidate_model 必须先于 data_id 检测，避免 model_id 被 "id" 误匹配为 data_id
SAMPLE_FIELDS: dict[str, list[str]] = {
    "task_id":         ["task_id", "任务id", "taskid"],
    "candidate_model": ["candidate_model", "model_id", "model", "模型", "候选模型"],
    "data_id":         ["data_id", "数据id", "dataid"],
    "query_id":        ["query_id", "queryid", "问题id"],
    "query":           ["query-turn-1", "query", "问题", "输入", "prompt"],
    "response":        ["response", "url", "网址", "eval_url"],
    "bridge_url":      ["bridge_url", "bridge_URL", "桥接url"],
    "auto_reason":     ["reason", "auto_reason", "原因", "judge_reason"],
}


def _norm(s: str) -> str:
    s = str(s or "")
    s = s.replace("（","(").replace("）",")").replace("：",":").replace("　"," ")
    return re.sub(r"\s+", "", s).lower()


class SchemaDetector:
    def __init__(self, headers: list[str]):
        self.headers = headers
        self._sample_cols: dict[str, int] = {}   # logical name -> col index
        self._dim_cols: dict[str, int] = {}       # dim code -> col index
        self._unknown_cols: list[int] = []

    def detect(self) -> "SchemaDetector":
        from .dimension_matcher import DimensionMatcher, _CODE_RE
        dm = DimensionMatcher(self.headers)
        dm.detect()
        self._dim_cols = {c: dm.col_of(c) for c in dm.found_codes()}

        # 样本字段
        used = set(self._dim_cols.values())
        for field, candidates in SAMPLE_FIELDS.items():
            for i, h in enumerate(self.headers):
                if i in used:
                    continue
                hn = _norm(h)
                if any(_norm(c) in hn or hn in _norm(c) for c in candidates):
                    self._sample_cols[field] = i
                    used.add(i)
                    break

        self._unknown_cols = [i for i in range(len(self.headers))
                               if i not in used and self.headers[i].strip()]
        return self

    @property
    def dim_cols(self) -> dict[str, int]:
        return self._dim_cols

    @property
    def sample_cols(self) -> dict[str, int]:
        return self._sample_cols

    def summary(self) -> dict:
        return {
            "total_headers": len(self.headers),
            "dim_cols": {k: self.headers[v] for k, v in self._dim_cols.items()},
            "sample_cols": {k: self.headers[v] for k, v in self._sample_cols.items()},
            "unknown_cols": [self.headers[i] for i in self._unknown_cols],
        }
