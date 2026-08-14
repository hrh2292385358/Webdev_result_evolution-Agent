"""分析主流程：数据对齐 → 指标计算 → 差异记录入库。"""
from __future__ import annotations

import json
import yaml
from pathlib import Path

from ..database import SessionLocal
from ..models import (
    DifferenceRecord, MetricResult, Task, UploadedFile, _now, _uid,
)
from ..core.data_normalizer import DataNormalizer, DataAligner
from ..core.metric_engine import MetricEngine

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def _parse_md_dim_to_cat(text: str) -> dict[str, str]:
    """从 Markdown 文件中提取维度代码→类别映射。
    支持两种格式：
    1. 章节标题含类别名（如 ## 一、功能层 Functionality），子节含编码属性行
    2. 属性表格中 | 编码 | Gx | 格式
    """
    import re
    # 类别标题模式：识别 Gateway/Functionality/Interactivity/Aesthetics/Content/DataPersistence
    category_patterns = [
        (re.compile(r'Gateway|门槛层', re.IGNORECASE), 'Gateway'),
        (re.compile(r'Functionality|功能层', re.IGNORECASE), 'Functionality'),
        (re.compile(r'Interactivity|交互层', re.IGNORECASE), 'Interactivity'),
        (re.compile(r'Aesthetics|美观层', re.IGNORECASE), 'Aesthetics'),
        (re.compile(r'Content|内容层', re.IGNORECASE), 'Content'),
        (re.compile(r'DataPersistence|数据层|数据持久', re.IGNORECASE), 'DataPersistence'),
    ]
    code_re = re.compile(r'\b(G[1-4]|F[1-4]|DP[1-4]|I[1-4]|A[1-4]|C[1-2])\b')

    mapping: dict[str, str] = {}
    current_cat = None

    for line in text.splitlines():
        # 检测章节标题切换类别
        if line.startswith('#'):
            for pat, cat in category_patterns:
                if pat.search(line):
                    current_cat = cat
                    break

        # 从属性表格行提取：| 编码 | G1 |
        if '|' in line and current_cat:
            cells = [c.strip() for c in line.split('|') if c.strip()]
            if len(cells) >= 2 and cells[0] in ('编码', 'code', 'Code'):
                m = code_re.search(cells[1])
                if m:
                    mapping[m.group(1).upper()] = current_cat

        # 从小节标题提取：### G1 · xxx 或 ### G1 xxx
        if line.startswith('###') and current_cat:
            m = code_re.search(line)
            if m:
                mapping[m.group(1).upper()] = current_cat

    return mapping


def _load_dim_rubrics(task_id: str, db) -> dict[str, str]:
    """加载每个维度的 rubric_points，供 LLM prompt 使用。"""
    return {code: info["rubric_points"]
            for code, info in _load_dim_info(task_id, db).items()}


def _load_dim_info(task_id: str, db) -> dict[str, dict]:
    """加载每个维度的完整信息（rubric_points、exemption、scale、name）。
    返回 {code: {rubric_points, exemption, scale, name}}。
    """
    skills_file = db.query(UploadedFile).filter(
        UploadedFile.task_id == task_id,
        UploadedFile.file_type == "skills",
    ).first()
    if skills_file:
        p = Path(skills_file.stored_path)
        if p.exists():
            try:
                text = p.read_text(encoding="utf-8")
                if p.suffix.lower() == ".md":
                    from ..routers.config_api import _parse_md_skills
                    cfg = _parse_md_skills(text)
                else:
                    cfg = yaml.safe_load(text) or {}
                result = {d["code"]: {
                    "rubric_points": d.get("rubric_points", "") or "",
                    "exemption":     d.get("exemption", "") or "",
                    "scale":         d.get("scale", "") or "",
                    "name":          d.get("name", "") or "",
                } for d in cfg.get("dimensions", []) if d.get("code")}
                if result:
                    return result
            except Exception:
                pass

    p = CONFIG_DIR / "dimensions.yaml"
    if not p.exists():
        return {}
    cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return {d["code"]: {
        "rubric_points": d.get("rubric_points", "") or "",
        "exemption":     d.get("exemption", "") or "",
        "scale":         d.get("scale", "") or "",
        "name":          d.get("name", "") or "",
    } for d in cfg.get("dimensions", []) if d.get("code")}


def _load_dim_to_cat(task_id: str, db) -> dict[str, str]:
    """优先读任务上传的 skills 文件（支持 YAML 和 Markdown），其次读 config/dimensions.yaml。"""
    skills_file = db.query(UploadedFile).filter(
        UploadedFile.task_id == task_id,
        UploadedFile.file_type == "skills",
    ).first()
    if skills_file:
        p = Path(skills_file.stored_path)
        if p.exists():
            try:
                text = p.read_text(encoding="utf-8")
                if p.suffix.lower() == ".md":
                    mapping = _parse_md_dim_to_cat(text)
                else:
                    cfg = yaml.safe_load(text) or {}
                    mapping = {d["code"]: d["category"] for d in cfg.get("dimensions", [])}
                if mapping:
                    return mapping
            except Exception:
                pass

    p = CONFIG_DIR / "dimensions.yaml"
    if not p.exists():
        return {}
    cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return {d["code"]: d["category"] for d in cfg.get("dimensions", [])}


def _load_weights(task_id: str, db) -> dict:
    """优先读任务上传的 weights 文件，其次读 config/weights.yaml。"""
    weights_file = db.query(UploadedFile).filter(
        UploadedFile.task_id == task_id,
        UploadedFile.file_type == "weights",
    ).first()
    if weights_file:
        p = Path(weights_file.stored_path)
        if p.exists():
            try:
                cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
                if cfg.get("category_weights"):
                    return cfg
            except Exception:
                pass

    p = CONFIG_DIR / "weights.yaml"
    if p.exists():
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return {}


def run_analysis_sync(task_id: str):
    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            return

        # 取文件路径
        gt_file = db.query(UploadedFile).filter(
            UploadedFile.task_id == task_id,
            UploadedFile.file_type == "ground_truth",
        ).first()
        ae_file = db.query(UploadedFile).filter(
            UploadedFile.task_id == task_id,
            UploadedFile.file_type == "auto_eval",
        ).first()

        if not gt_file or not ae_file:
            task.status = "failed"; task.updated_at = _now(); db.commit()
            return

        score_range = [int(x) for x in (task.score_range or "0,1,2").split(",")]

        # 1. 标准化
        gt_records   = DataNormalizer(gt_file.stored_path,  score_range).normalize()
        auto_records = DataNormalizer(ae_file.stored_path,  score_range).normalize()

        # 2. 对齐
        aligned, auto_only_count = DataAligner(gt_records, auto_records).align()

        # 3. 计算指标（使用任务级 skills/weights，fallback 到 config/）
        dim_to_cat  = _load_dim_to_cat(task_id, db)
        dim_info    = _load_dim_info(task_id, db)
        dim_rubrics = {code: info["rubric_points"] for code, info in dim_info.items()}
        engine = MetricEngine(aligned, score_range, dim_to_cat)
        results = engine.compute_all()
        results["overall"]["data_quality"]["auto_only_cells"] = auto_only_count

        # 把任务级权重注入 results 供 WeightAdvisor 使用
        task_weights = _load_weights(task_id, db)
        results["__task_weights__"] = task_weights

        # 4. 清旧指标 → 写新指标
        overall_with_warnings = {
            **results["overall"],
            "model_warnings": results.get("model_warnings", []),
        }
        db.query(MetricResult).filter(MetricResult.task_id == task_id).delete()
        db.add(MetricResult(id=_uid(), task_id=task_id, scope="overall",
                            metrics=overall_with_warnings))
        for key, m in results["by_category"].items():
            db.add(MetricResult(id=_uid(), task_id=task_id,
                                scope="category", scope_key=key, metrics=m))
        for key, m in results["by_dimension"].items():
            db.add(MetricResult(id=_uid(), task_id=task_id,
                                scope="dimension", scope_key=key, metrics=m))
        for key, m in results["by_model"].items():
            db.add(MetricResult(id=_uid(), task_id=task_id,
                                scope="model", scope_key=key, metrics=m))

        # 5. 错误归因
        from ..core.error_clusterer import ErrorClusterer
        judge_model = task.judge_model or ""
        clusterer = ErrorClusterer(aligned, results, use_llm=True,
                                   judge_model=judge_model, dim_rubrics=dim_rubrics)
        dim_clusters = clusterer.cluster()
        llm_summaries = clusterer.enrich_with_llm(dim_clusters)

        # 差异记录入库（含所有记录：差异、空值、豁免）
        db.query(DifferenceRecord).filter(DifferenceRecord.task_id == task_id).delete()
        for r in aligned:
            gt_score  = r.get("ground_truth_score")
            auto_score = r.get("auto_score")
            gt_exempt  = r.get("gt_is_exempt", False)
            auto_exempt = r.get("auto_is_exempt", False)
            has_auto   = r.get("has_auto", False)

            # 归因
            if gt_exempt or auto_exempt:
                cause = "豁免/不适用"
            elif gt_score is None:
                cause = "GT空数据"
            elif auto_score is None:
                cause = "AutoEval空数据（漏评或流水线跳过）"
            elif r.get("delta") is None:
                cause = "无法计算差异"
            else:
                cause = clusterer._rule_classify(r)

            is_severe = (gt_score == 0 and auto_score == 2) or \
                        (gt_score == 2 and auto_score == 0)

            db.add(DifferenceRecord(
                id=_uid(), task_id=task_id,
                data_id=str(r.get("data_id") or ""),
                query_id=str(r.get("query_id") or ""),
                candidate_model=str(r.get("candidate_model") or ""),
                dimension_code=r.get("dimension_code", ""),
                ground_truth_score=gt_score,
                auto_score=auto_score,
                delta=r.get("delta"),
                auto_reason=r.get("auto_reason"),
                root_cause_category=cause,
                is_severe_error=is_severe,
                extra={
                    "gt_is_exempt": gt_exempt,
                    "auto_is_exempt": auto_exempt,
                    "has_auto": has_auto,
                },
            ))

        # 6. 更新任务状态
        task.status = "generating_recommendations"
        task.updated_at = _now()
        db.commit()

        # 7. 生成建议（含 LLM 增强）
        _run_advisors(task_id, db, aligned, results, llm_summaries, dim_info)

        task.status = "completed"; task.updated_at = _now(); db.commit()

    except Exception:
        import traceback; traceback.print_exc()
        t = db.query(Task).filter(Task.id == task_id).first()
        if t:
            t.status = "failed"; t.updated_at = _now(); db.commit()
    finally:
        db.close()


def _run_advisors(task_id: str, db, aligned: list[dict], results: dict,
                  llm_summaries: dict = None, dim_info: dict = None):
    from ..advisors.skill_advisor import SkillAdvisor
    from ..advisors.strategy_advisor import StrategyAdvisor
    from ..advisors.weight_advisor import WeightAdvisor
    from ..models import Recommendation

    llm_summaries = llm_summaries or {}
    dim_info      = dim_info or {}
    dim_rubrics   = {code: info["rubric_points"] for code, info in dim_info.items()}
    db.query(Recommendation).filter(Recommendation.task_id == task_id).delete()

    for rec in SkillAdvisor(task_id, aligned, results, dim_info).generate():
        code = rec.get("target_dimension", "")
        if code and code in llm_summaries:
            rec["content"]["llm_summary"] = llm_summaries[code]
            rec["llm_generated"] = bool(llm_summaries[code] and
                                        "失败" not in llm_summaries[code])
        db.add(Recommendation(id=_uid(), task_id=task_id, **rec))

    for rec in StrategyAdvisor(task_id, aligned, results).generate():
        db.add(Recommendation(id=_uid(), task_id=task_id, **rec))

    # WeightAdvisor 传入任务级权重配置
    task_weights = results.pop("__task_weights__", {})
    for rec in WeightAdvisor(task_id, results, task_weights).generate():
        db.add(Recommendation(id=_uid(), task_id=task_id, **rec))

    db.commit()
