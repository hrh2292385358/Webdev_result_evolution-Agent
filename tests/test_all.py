"""核心单元测试套件。"""
from __future__ import annotations

import pytest
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
GT_PATH  = FIXTURES / "sample_gt.xlsx"
AE_PATH  = FIXTURES / "sample_auto.xlsx"

# ---------------------------------------------------------------------------
# 1. 文件解析测试
# ---------------------------------------------------------------------------
class TestFileParser:
    def test_load_valid(self):
        from backend.parsers.file_parser import FileParser
        fp = FileParser(GT_PATH).load()
        info = fp.basic_info()
        assert len(info["sheets"]) >= 1
        fp.close()

    def test_load_missing(self, tmp_path):
        from backend.parsers.file_parser import FileParser, FileParseError
        with pytest.raises(FileParseError):
            FileParser(tmp_path / "notexist.xlsx").load()

    def test_get_rows(self):
        from backend.parsers.file_parser import FileParser
        fp = FileParser(GT_PATH).load()
        rows = fp.get_rows()
        assert len(rows) == 6
        fp.close()

    def test_no_duplicate_headers(self):
        from backend.parsers.file_parser import FileParser
        fp = FileParser(GT_PATH).load()
        dupes = fp.check_duplicate_headers()
        assert dupes == []
        fp.close()


# ---------------------------------------------------------------------------
# 2. 维度匹配测试
# ---------------------------------------------------------------------------
class TestDimensionMatcher:
    def test_exact_codes(self):
        from backend.parsers.dimension_matcher import DimensionMatcher
        headers = ["data_id", "G1", "F1", "F2", "I4", "A1", "C1"]
        dm = DimensionMatcher(headers).detect()
        assert "G1" in dm.found_codes()
        assert "F1" in dm.found_codes()
        assert "I4" in dm.found_codes()

    def test_code_with_name(self):
        from backend.parsers.dimension_matcher import DimensionMatcher
        headers = ["data_id", "F1 功能逻辑正确", "A3_色彩协调"]
        dm = DimensionMatcher(headers).detect()
        assert "F1" in dm.found_codes()
        assert "A3" in dm.found_codes()

    def test_missing_dimension(self):
        from backend.parsers.dimension_matcher import DimensionMatcher
        gt_dm  = DimensionMatcher(["G1","G2","F1","F2"]).detect()
        ae_dm  = DimensionMatcher(["G1","G2","F1"]).detect()   # F2 缺失
        report = gt_dm.alignment_report(ae_dm)
        issues_text = [i["message"] for i in report["issues"]]
        assert any("F2" in t for t in issues_text)

    def test_auto_file_has_extra(self):
        from backend.parsers.dimension_matcher import DimensionMatcher
        gt_dm  = DimensionMatcher(["G1","F1"]).detect()
        ae_dm  = DimensionMatcher(["G1","F1","DP1"]).detect()   # DP1 多余
        report = gt_dm.alignment_report(ae_dm)
        issues_text = [i["message"] for i in report["issues"]]
        assert any("DP1" in t for t in issues_text)


# ---------------------------------------------------------------------------
# 3. 样本乱序匹配测试
# ---------------------------------------------------------------------------
class TestSampleMatcher:
    def _make_rows(self, data):
        return [{"data_id": d, "query_id": q, "candidate_model": m}
                for d, q, m in data]

    def test_exact_match(self):
        from backend.parsers.sample_matcher import SampleMatcher
        gt   = self._make_rows([("d1","q1","A"),("d2","q2","B")])
        auto = self._make_rows([("d2","q2","B"),("d1","q1","A")])  # 顺序不同
        sm   = SampleMatcher(gt, auto)
        s    = sm.stats
        assert s["matched"] == 2
        assert s["gt_only"] == 0

    def test_gt_only(self):
        from backend.parsers.sample_matcher import SampleMatcher
        gt   = self._make_rows([("d1","q1","A"),("d2","q2","B")])
        auto = self._make_rows([("d1","q1","A")])
        s    = SampleMatcher(gt, auto).stats
        assert s["gt_only"] == 1

    def test_duplicate_rows(self):
        from backend.parsers.sample_matcher import SampleMatcher
        gt   = self._make_rows([("d1","q1","A")])
        auto = self._make_rows([("d1","q1","A"),("d1","q1","A")])
        s    = SampleMatcher(gt, auto).stats
        assert s["duplicates"] > 0


# ---------------------------------------------------------------------------
# 4. 指标计算测试
# ---------------------------------------------------------------------------
class TestMetricEngine:
    def _aligned(self):
        return [
            {"gt_is_valid":True,"auto_is_valid":True,"gt_is_exempt":False,"auto_is_exempt":False,
             "ground_truth_score":2,"auto_score":2,"delta":0,"dimension_code":"F1","candidate_model":"A"},
            {"gt_is_valid":True,"auto_is_valid":True,"gt_is_exempt":False,"auto_is_exempt":False,
             "ground_truth_score":2,"auto_score":1,"delta":-1,"dimension_code":"F1","candidate_model":"A"},
            {"gt_is_valid":True,"auto_is_valid":True,"gt_is_exempt":False,"auto_is_exempt":False,
             "ground_truth_score":0,"auto_score":2,"delta":2,"dimension_code":"F2","candidate_model":"B"},
            {"gt_is_valid":True,"auto_is_valid":True,"gt_is_exempt":False,"auto_is_exempt":False,
             "ground_truth_score":1,"auto_score":1,"delta":0,"dimension_code":"F2","candidate_model":"B"},
        ]

    def test_exact_match(self):
        from backend.core.metric_engine import MetricEngine
        m = MetricEngine(self._aligned()).compute_all()["overall"]
        assert m["exact_match"] == pytest.approx(0.5)

    def test_within1(self):
        from backend.core.metric_engine import MetricEngine
        m = MetricEngine(self._aligned()).compute_all()["overall"]
        assert m["within1"] == pytest.approx(0.75)

    def test_mae(self):
        from backend.core.metric_engine import MetricEngine
        m = MetricEngine(self._aligned()).compute_all()["overall"]
        assert m["mae"] == pytest.approx(0.75)

    def test_bias(self):
        from backend.core.metric_engine import MetricEngine
        m = MetricEngine(self._aligned()).compute_all()["overall"]
        assert m["bias"] == pytest.approx(0.25)

    def test_severe_errors(self):
        from backend.core.metric_engine import MetricEngine
        m = MetricEngine(self._aligned()).compute_all()["overall"]
        assert m["severe_errors"] == 1

    def test_precision_recall_keys(self):
        from backend.core.metric_engine import MetricEngine
        prf = MetricEngine(self._aligned()).compute_all()["overall"]["precision_recall_f1"]
        assert "macro_f1" in prf
        assert "weighted_f1" in prf

    def test_coverage(self):
        from backend.core.metric_engine import MetricEngine
        m = MetricEngine(self._aligned()).compute_all()["overall"]
        # 4 valid / 4 total = 1.0（测试数据全部有效）
        assert m["coverage"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 5. 权重验证测试
# ---------------------------------------------------------------------------
class TestWeightValidator:
    def test_sum_not_100(self):
        from backend.core.weight_validator import WeightValidator
        wv = WeightValidator({"category_weights":{"F":31,"I":28,"A":31,"C":12}})
        r  = wv.validate()
        assert r["weight_sum"] == 102
        assert any("102" in i["message"] for i in r["issues"])

    def test_dp_missing_weight(self):
        from backend.core.weight_validator import WeightValidator
        cfg = {
            "category_weights": {"F":31,"I":28,"A":31,"C":10},
            "categories": {"F":["F1"],"DataPersistence":["DP1"]},
        }
        r = WeightValidator(cfg).validate()
        assert any("DataPersistence" in i["message"] for i in r["issues"])

    def test_negative_weight(self):
        from backend.core.weight_validator import WeightValidator
        r = WeightValidator({"category_weights":{"F":-5}}).validate()
        assert r["status"] == "fail"

    def test_weight_normalization(self):
        from backend.advisors.weight_advisor import _normalize
        w = {"F":31,"I":28,"A":31,"C":12}
        n = _normalize(w)
        assert abs(sum(n.values()) - 100) < 0.1


# ---------------------------------------------------------------------------
# 6. 端到端 API 流程测试
# ---------------------------------------------------------------------------
class TestAPIFlow:
    def test_health(self):
        from backend.main import app
        from fastapi.testclient import TestClient
        c = TestClient(app)
        r = c.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_create_and_upload(self):
        from backend.main import app
        from fastapi.testclient import TestClient
        c = TestClient(app)

        # 创建任务
        r = c.post("/api/tasks", json={"name":"pytest任务","score_range":"0,1,2"})
        assert r.json()["success"]
        tid = r.json()["data"]["id"]

        # 上传 GT
        with open(GT_PATH, "rb") as f:
            r = c.post(f"/api/tasks/{tid}/upload/ground-truth",
                       files={"file": ("gt.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
        assert r.json()["success"], r.text

        # 上传 AutoEval
        with open(AE_PATH, "rb") as f:
            r = c.post(f"/api/tasks/{tid}/upload/auto-eval",
                       files={"file": ("ae.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
        assert r.json()["success"], r.text

        # 检查维度
        r = c.post(f"/api/tasks/{tid}/check")
        j = r.json()
        assert j["success"], r.text
        assert j["data"]["overall_status"] in ("pass", "warn", "fail")

        print(f"check status: {j['data']['overall_status']}")
        print(f"sample matched: {j['data']['sample_check']['matched']}")
