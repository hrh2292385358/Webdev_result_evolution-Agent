"""生成示例测试 Excel 文件。"""
from __future__ import annotations

from pathlib import Path
import openpyxl

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURES.mkdir(exist_ok=True)


def make_gt(path: Path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    # 表头
    ws.append([
        "data_id", "query_id", "candidate_model", "query",
        "response",
        "G1", "G2", "G3", "G4",
        "F1", "F2", "F3", "F4",
        "I1", "I2", "I3", "I4",
        "A1", "A2", "A3", "A4",
        "C1", "C2",
    ])
    rows = [
        # data_id, query_id, model, query, url, G1..G4, F1..F4, I1..I4, A1..A4, C1,C2
        ("d1","q1","A","搜索功能","http://a.test",1,1,1,1, 2,2,2,1, 2,1,2,2, 2,2,1,2, 1,0),
        ("d1","q1","B","搜索功能","http://b.test",1,1,1,0, 1,2,1,1, 1,1,1,2, 2,1,2,1, 2,1),
        ("d2","q2","A","登录页面","http://c.test",1,1,1,1, 2,1,2,2, 2,2,1,1, 1,2,2,1, 0,None),
        ("d2","q2","B","登录页面","http://d.test",1,1,0,1, 1,1,1,0, 1,0,1,1, 2,1,1,2, 1,1),
        # 行顺序不同（用于测试乱序匹配）
        ("d3","q3","B","数据图表","http://f.test",1,1,1,1, 2,2,2,2, 2,2,2,1, 2,2,2,2, 2,1),
        ("d3","q3","A","数据图表","http://e.test",1,1,1,1, 1,1,2,1, 1,1,2,2, 1,1,1,2, 1,2),
    ]
    for r in rows:
        ws.append(list(r))
    wb.save(path)


def make_auto(path: Path):
    """Auto Eval：故意引入部分偏差和一个缺失维度（无 C2 列）。"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append([
        "data_id", "query_id", "candidate_model", "query",
        "response",
        "G1", "G2", "G3", "G4",
        "F1 功能逻辑正确", "F2", "F3", "F4",   # F1 列名含中文（测试辅助匹配）
        "I1", "I2", "I3", "I4",
        "A1", "A2", "A3", "A4",
        "C1",
        "reason",
    ])
    rows = [
        # 部分分值有偏差，C2 整列缺失
        ("d1","q1","A","搜索功能","http://a.test",1,1,1,1, 2,2,2,2, 2,1,2,2, 2,2,1,2, 1,"评分正常"),
        ("d1","q1","B","搜索功能","http://b.test",1,1,1,0, 2,2,1,1, 1,1,1,2, 2,1,2,1, 2,"功能偏高"),
        ("d2","q2","A","登录页面","http://c.test",1,1,1,1, 2,1,2,2, 2,2,1,1, 1,2,2,1, 0,"图片无法评估"),
        ("d2","q2","B","登录页面","http://d.test",1,1,0,1, 0,1,1,0, 1,0,1,1, 2,1,1,2, 1,"确定性规则触发"),
        # 行顺序打乱
        ("d3","q3","A","数据图表","http://e.test",1,1,1,1, 2,1,2,2, 1,1,2,2, 2,1,1,2, 1,"视觉质量一般"),
        ("d3","q3","B","数据图表","http://f.test",1,1,1,1, 2,2,2,2, 2,2,2,1, 2,2,2,2, 2,"整体优秀"),
    ]
    for r in rows:
        ws.append(list(r))
    wb.save(path)


if __name__ == "__main__":
    make_gt(FIXTURES / "sample_gt.xlsx")
    make_auto(FIXTURES / "sample_auto.xlsx")
    print("fixtures created:", FIXTURES)
