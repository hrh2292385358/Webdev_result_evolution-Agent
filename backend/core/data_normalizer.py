"""DataNormalizer + DataAligner：将 GT 和 AutoEval 转为标准长表并对齐。"""
from __future__ import annotations

from typing import Any, Optional

from ..parsers.file_parser import FileParser
from ..parsers.schema_detector import SchemaDetector
from ..parsers.dimension_matcher import DimensionMatcher, STANDARD_CODES


def _to_float(v: Any) -> Optional[float]:
    """将单元格值转为 float，无法转换返回 None。"""
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ("", "na", "n/a", "不适用", "豁免", "exempt", "-"):
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _is_exempt(v: Any) -> bool:
    if v is None:
        return False
    return str(v).strip().lower() in ("exempt", "豁免", "不适用", "na", "n/a")


class DataNormalizer:
    """
    把一份 Excel（GT 或 AutoEval）转成长表，每条记录 = 一个样本×一个维度。
    """

    def __init__(self, file_path: str, score_range: list[int] = None):
        self.file_path = file_path
        self.score_range = score_range or [0, 1, 2]

    def normalize(self) -> list[dict]:
        fp = FileParser(self.file_path).load()
        headers = fp.get_headers()
        rows = fp.get_rows()
        fp.close()

        sd = SchemaDetector(headers).detect()
        dm = DimensionMatcher(headers).detect()

        records = []
        for row in rows:
            # 样本字段
            sample = {}
            for field, idx in sd.sample_cols.items():
                col_name = headers[idx] if idx < len(headers) else None
                sample[field] = row.get(col_name) if col_name else None

            # 每个识别到的维度生成一条记录
            for code in dm.found_codes():
                col_idx = dm.col_of(code)
                col_name = headers[col_idx] if col_idx is not None else None
                raw_val = row.get(col_name) if col_name else None

                score = _to_float(raw_val)
                exempt = _is_exempt(raw_val)
                is_valid = (score is not None and not exempt
                            and score in self.score_range)
                invalid_reason = None
                if score is None and not exempt:
                    invalid_reason = f"空值或无法解析：{raw_val!r}"
                elif score is not None and score not in self.score_range:
                    invalid_reason = f"分值 {score} 超出合法范围 {self.score_range}"

                records.append({
                    **sample,
                    "dimension_code": code,
                    "raw_value": str(raw_val) if raw_val is not None else None,
                    "score": score,
                    "is_exempt": exempt,
                    "is_valid": is_valid,
                    "invalid_reason": invalid_reason,
                })

        return records


class DataAligner:
    """
    对齐 GT 长表和 AutoEval 长表，生成包含 delta 的对齐记录。
    匹配键：data_id + query_id + candidate_model + dimension_code
    """

    def __init__(self, gt_records: list[dict], auto_records: list[dict]):
        self.gt_records = gt_records
        self.auto_records = auto_records

    @staticmethod
    def _key(r: dict) -> str:
        did   = str(r.get("data_id") or "").strip()
        qid   = str(r.get("query_id") or "").strip()
        model = str(r.get("candidate_model") or "").strip()
        code  = str(r.get("dimension_code") or "").strip()
        return f"{did}||{qid}||{model}||{code}"

    def align(self) -> tuple[list[dict], int]:
        """返回 (aligned_records, auto_only_count)。
        auto_only_count：AutoEval 中有但 GT 中没有的记录数。
        """
        auto_index: dict[str, dict] = {}
        for r in self.auto_records:
            k = self._key(r)
            if k not in auto_index:
                auto_index[k] = r

        matched_keys: set[str] = set()
        aligned = []
        for gr in self.gt_records:
            k = self._key(gr)
            ar = auto_index.get(k)
            if ar is not None:
                matched_keys.add(k)

            gt_score   = gr.get("score")
            auto_score = ar.get("score") if ar else None
            delta = (auto_score - gt_score
                     if gt_score is not None and auto_score is not None
                     else None)

            aligned.append({
                "data_id":           gr.get("data_id"),
                "query_id":          gr.get("query_id"),
                "query":             gr.get("query"),
                "candidate_model":   gr.get("candidate_model"),
                "response":          gr.get("response"),
                "bridge_url":        gr.get("bridge_url"),
                "dimension_code":    gr.get("dimension_code"),
                "ground_truth_score": gt_score,
                "auto_score":        auto_score,
                "delta":             delta,
                "absolute_delta":    abs(delta) if delta is not None else None,
                "auto_reason":       ar.get("auto_reason") if ar else None,
                "gt_is_valid":       gr.get("is_valid", False),
                "auto_is_valid":     ar.get("is_valid", False) if ar else False,
                "gt_is_exempt":      gr.get("is_exempt", False),
                "auto_is_exempt":    ar.get("is_exempt", False) if ar else False,
                "has_auto":          ar is not None,
            })

        auto_only_count = sum(1 for k in auto_index if k not in matched_keys)
        return aligned, auto_only_count
