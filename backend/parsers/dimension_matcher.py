"""DimensionMatcher：识别并对齐 GT 和 AutoEval 文件中的评分维度列。"""
from __future__ import annotations

import re
from typing import Optional

import yaml
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"

# 22个标准维度代码
STANDARD_CODES = [
    "G1","G2","G3","G4",
    "F1","F2","F3","F4",
    "DP1","DP2","DP3","DP4",
    "I1","I2","I3","I4",
    "A1","A2","A3","A4",
    "C1","C2",
]

# 中英文名称辅助匹配
DIM_ALIASES: dict[str, list[str]] = {
    "G1": ["推理与部署","部署完整性"],
    "G2": ["代码正常渲染","正常渲染"],
    "G3": ["运行时稳定","稳定性"],
    "G4": ["需求意图","意图匹配"],
    "F1": ["功能逻辑","功能正确"],
    "F2": ["数据展示","展示正确"],
    "F3": ["响应式","适配"],
    "F4": ["控制台错误","console"],
    "DP1": ["鉴权","auth"],
    "DP2": ["crud","增删改查"],
    "DP3": ["持久化","刷新"],
    "DP4": ["数据隔离","隔离"],
    "I1": ["交互反馈","反馈"],
    "I2": ["过渡效果","transition"],
    "I3": ["动画流畅","animation"],
    "I4": ["用户体验","ux"],
    "A1": ["布局合理","布局"],
    "A2": ["排版规范","排版"],
    "A3": ["色彩协调","配色"],
    "A4": ["设计感","视觉"],
    "C1": ["内容图片","图片质量"],
    "C2": ["音视频","media"],
}

_CODE_RE = re.compile(r'\b(G[1-4]|F[1-4]|DP[1-4]|I[1-4]|A[1-4]|C[1-2])\b', re.IGNORECASE)


def _norm(s: str) -> str:
    """标准化：去空格、转小写、全角转半角。"""
    s = str(s or "")
    s = s.replace("（","(").replace("）",")").replace("：",":").replace("　"," ")
    return re.sub(r"\s+", "", s).lower()


class DimensionMatcher:
    def __init__(self, headers: list[str]):
        self.headers = headers
        self._mapping: dict[str, int] = {}   # code -> col index (0-based)
        self._suspect: dict[str, list[int]] = {}  # code -> 疑似列列表

    def detect(self) -> "DimensionMatcher":
        """扫描表头，识别维度列。"""
        self._mapping.clear()
        self._suspect.clear()

        for i, h in enumerate(self.headers):
            # 优先：精确代码匹配
            m = _CODE_RE.search(h.replace("_", " "))
            if m:
                code = m.group(1).upper()
                if code not in self._mapping:
                    self._mapping[code] = i
                continue
            # 次选：别名模糊匹配
            hn = _norm(h)
            for code, aliases in DIM_ALIASES.items():
                if code in self._mapping:
                    continue
                if any(_norm(a) in hn for a in aliases):
                    self._suspect.setdefault(code, []).append(i)

        return self

    def found_codes(self) -> list[str]:
        return list(self._mapping.keys())

    def col_of(self, code: str) -> Optional[int]:
        return self._mapping.get(code.upper())

    def suspect_cols(self, code: str) -> list[int]:
        return self._suspect.get(code.upper(), [])

    def apply_manual(self, code: str, col_index: int):
        """用户手动确认映射。"""
        self._mapping[code.upper()] = col_index

    def alignment_report(self, other: "DimensionMatcher") -> dict:
        """比较两个文件的维度覆盖情况，返回对齐报告。"""
        self_codes  = set(self.found_codes())
        other_codes = set(other.found_codes())
        all_codes   = set(STANDARD_CODES)

        dimensions = []
        for code in STANDARD_CODES:
            in_self  = code in self_codes
            in_other = code in other_codes
            if in_self and in_other:
                status = "pass"
            elif in_self or in_other:
                status = "warn"
            else:
                status = "info"   # 两边都没有，可能不适用
            dimensions.append({
                "code": code,
                "in_gt": in_self,
                "in_auto": in_other,
                "status": status,
            })

        issues = []
        gt_only   = self_codes - other_codes
        auto_only = other_codes - self_codes
        both_missing = set(STANDARD_CODES) - self_codes - other_codes
        if gt_only:
            issues.append({"level":"warn","message":f"GT有但AutoEval缺失的维度：{', '.join(sorted(gt_only))}"})
        if auto_only:
            issues.append({"level":"warn","message":f"AutoEval有但GT缺失的维度：{', '.join(sorted(auto_only))}"})
        if both_missing:
            issues.append({"level":"warn","message":f"GT和AutoEval均未包含以下标准维度（将被跳过，不影响已有维度的分析）：{', '.join(sorted(both_missing))}"})
        # 疑似匹配提示：只对没有精确匹配的维度才提示
        for code, cols in self._suspect.items():
            if code in self._mapping:
                continue  # 已精确匹配，忽略疑似列
            issues.append({"level":"info","message":f"GT维度 {code} 未精确匹配，疑似列：{[self.headers[c] for c in cols]}"})

        return {"dimensions": dimensions, "issues": issues}
