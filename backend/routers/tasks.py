"""文件上传与维度检查路由。"""
from __future__ import annotations

import re
import shutil
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import UPLOADS_DIR, REPORTS_DIR
from ..database import get_db
from ..models import (
    ApiResponse, CheckResult, DifferenceRecord, ExportedReport,
    FieldMapping, MetricResult, Recommendation, RunLog,
    Task, TaskCreate, TaskOut, UploadedFile, WeightScenario, _now, _uid,
)
from ..parsers.file_parser import FileParser, FileParseError
from ..parsers.dimension_matcher import DimensionMatcher, STANDARD_CODES
from ..parsers.sample_matcher import SampleMatcher
from ..parsers.schema_detector import SchemaDetector
from ..core.weight_validator import WeightValidator

router = APIRouter()


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _get_task_or_404(task_id: str, db: Session) -> Task:
    t = db.query(Task).filter(Task.id == task_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="任务不存在")
    return t


def _safe_filename(task_id: str, file_type: str, original: str) -> str:
    suffix = Path(original).suffix.lower() or ".xlsx"
    return f"{task_id}_{file_type}_{int(time.time())}{suffix}"


# ---------------------------------------------------------------------------
# 任务 CRUD
# ---------------------------------------------------------------------------

@router.post("/tasks", response_model=ApiResponse)
def create_task(payload: TaskCreate, db: Session = Depends(get_db)):
    task = Task(id=_uid(), **payload.model_dump(), status="created")
    db.add(task)
    db.commit()
    db.refresh(task)
    return ApiResponse(success=True, data=TaskOut.model_validate(task).model_dump())


@router.get("/tasks", response_model=ApiResponse)
def list_tasks(db: Session = Depends(get_db)):
    tasks = db.query(Task).order_by(Task.created_at.desc()).all()
    return ApiResponse(success=True,
                       data=[TaskOut.model_validate(t).model_dump() for t in tasks])


@router.get("/tasks/{task_id}", response_model=ApiResponse)
def get_task(task_id: str, db: Session = Depends(get_db)):
    t = _get_task_or_404(task_id, db)
    return ApiResponse(success=True, data=TaskOut.model_validate(t).model_dump())


# ---------------------------------------------------------------------------
# 文件上传
# ---------------------------------------------------------------------------

@router.post("/tasks/{task_id}/upload/{file_type}", response_model=ApiResponse)
async def upload_file(
    task_id: str,
    file_type: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if file_type not in ("ground-truth", "auto-eval", "skills", "weights"):
        raise HTTPException(400, "file_type 必须是 ground-truth、auto-eval、skills 或 weights")

    task = _get_task_or_404(task_id, db)

    # 防路径穿越
    safe_name = _safe_filename(task_id, file_type.replace("-","_"), file.filename or "upload.xlsx")
    dest = UPLOADS_DIR / safe_name
    content = await file.read()
    dest.write_bytes(content)

    # skills / weights 文件不做 Excel 行列解析，直接存路径
    ft_key = file_type.replace("-", "_")
    if file_type in ("skills", "weights"):
        db.query(UploadedFile).filter(
            UploadedFile.task_id == task_id,
            UploadedFile.file_type == ft_key,
        ).delete()
        uf = UploadedFile(
            id=_uid(), task_id=task_id, file_type=ft_key,
            original_name=file.filename or safe_name,
            stored_path=str(dest),
            n_rows=0, n_sheets=1, detected_schema={},
        )
        db.add(uf)
        db.commit()
        return ApiResponse(success=True, data={
            "file_type": ft_key,
            "original_name": file.filename or safe_name,
        })

    # 快速解析基础信息
    try:
        fp = FileParser(dest).load()
        info = fp.basic_info()
        sheet0 = info["sheets"][0] if info["sheets"] else {}
        fp.close()
    except FileParseError as e:
        dest.unlink(missing_ok=True)
        return ApiResponse(success=False, error=str(e))

    # 记录到数据库
    # 删除同类型旧文件记录
    db.query(UploadedFile).filter(
        UploadedFile.task_id == task_id,
        UploadedFile.file_type == ft_key,
    ).delete()

    uf = UploadedFile(
        id=_uid(), task_id=task_id, file_type=ft_key,
        original_name=file.filename or safe_name,
        stored_path=str(dest),
        n_rows=sheet0.get("max_row", 0) - 1,
        n_sheets=len(info["sheets"]),
        detected_schema=info,
    )
    db.add(uf)
    task.status = "files_uploaded"
    task.updated_at = _now()
    db.commit()

    return ApiResponse(success=True, data={
        "file_type": ft_key,
        "original_name": uf.original_name,
        "n_rows": uf.n_rows,
        "n_sheets": uf.n_sheets,
        "schema": info,
    })


# ---------------------------------------------------------------------------
# 维度/样本/权重检查
# ---------------------------------------------------------------------------

@router.post("/tasks/{task_id}/check", response_model=ApiResponse)
def run_check(task_id: str, db: Session = Depends(get_db)):
    task = _get_task_or_404(task_id, db)

    # 取上传文件
    gt_file  = db.query(UploadedFile).filter(
        UploadedFile.task_id == task_id, UploadedFile.file_type == "ground_truth").first()
    ae_file  = db.query(UploadedFile).filter(
        UploadedFile.task_id == task_id, UploadedFile.file_type == "auto_eval").first()

    if not gt_file or not ae_file:
        return ApiResponse(success=False, error="请先上传 Ground Truth 和 Auto Eval 两个文件")

    file_checks = []
    overall_status = "pass"

    # ---- 1. 文件基础检查 --------------------------------------------------
    for label, path in [("GT", gt_file.stored_path), ("AutoEval", ae_file.stored_path)]:
        try:
            fp = FileParser(path).load()
            info = fp.basic_info()
            dupes = fp.check_duplicate_headers()
            fp.close()
            file_checks.append({"status":"pass","message":f"{label}：可读取，共{len(info['sheets'])}个Sheet，首Sheet {info['sheets'][0]['max_row']-1}行数据"})
            if dupes:
                file_checks.append({"status":"warn","message":f"{label}：存在重复列名：{dupes}"})
        except FileParseError as e:
            file_checks.append({"status":"fail","message":f"{label}：{e}"})
            overall_status = "fail"

    if overall_status == "fail":
        _save_check(db, task_id, "overall", "fail",
                    {"overall_status":"fail","file_checks":file_checks})
        task.status = "check_failed"; task.updated_at = _now(); db.commit()
        return ApiResponse(success=True, data={"overall_status":"fail",
            "file_checks":file_checks,"dimension_check":None,
            "sample_check":None,"weight_check":None})

    # ---- 2. 维度检查 -------------------------------------------------------
    gt_fp  = FileParser(gt_file.stored_path).load()
    ae_fp  = FileParser(ae_file.stored_path).load()
    gt_headers  = gt_fp.get_headers()
    ae_headers  = ae_fp.get_headers()

    gt_dm = DimensionMatcher(gt_headers).detect()
    ae_dm = DimensionMatcher(ae_headers).detect()
    dim_report = gt_dm.alignment_report(ae_dm)

    # 阻塞：两边维度交集为空
    matched_dims = set(gt_dm.found_codes()) & set(ae_dm.found_codes())
    if not matched_dims:
        dim_report["issues"].append({"level":"error","message":"GT和AutoEval没有任何共同维度，无法对齐"})
        overall_status = "fail"

    # ---- 3. 样本对齐检查 ---------------------------------------------------
    gt_sd  = SchemaDetector(gt_headers).detect()
    ae_sd  = SchemaDetector(ae_headers).detect()
    gt_rows = gt_fp.get_rows()
    ae_rows = ae_fp.get_rows()
    gt_fp.close(); ae_fp.close()

    # 将列索引映射为字段名
    def remap(rows: list[dict], sd: SchemaDetector) -> list[dict]:
        out = []
        for r in rows:
            mapped = {}
            for field, idx in sd.sample_cols.items():
                col_name = list(r.keys())[idx] if idx < len(r) else None
                if col_name:
                    mapped[field] = r.get(col_name)
            # 保留原始数据备用
            mapped["_raw"] = r
            out.append(mapped)
        return out

    gt_mapped  = remap(gt_rows, gt_sd)
    ae_mapped  = remap(ae_rows, ae_sd)
    sm = SampleMatcher(gt_mapped, ae_mapped)
    sample_stats = sm.stats

    if any(i["level"]=="error" for i in sample_stats["issues"]):
        overall_status = "fail"
    elif any(i["level"]=="warn" for i in sample_stats["issues"]) and overall_status == "pass":
        overall_status = "warn"

    # ---- 4. 权重检查 -------------------------------------------------------
    wv = WeightValidator()
    weight_result = wv.validate()
    if weight_result["status"] == "fail":
        overall_status = "fail"
    elif weight_result["status"] == "warn" and overall_status == "pass":
        overall_status = "warn"

    # 维度检查也可能产生 warn
    if any(i["level"]=="warn" for i in dim_report["issues"]) and overall_status == "pass":
        overall_status = "warn"

    result = {
        "overall_status": overall_status,
        "file_checks": file_checks,
        "dimension_check": dim_report,
        "sample_check": {
            "matched": sample_stats["matched"],
            "gt_only": sample_stats["gt_only"],
            "auto_only": sample_stats["auto_only"],
            "duplicates": sample_stats["duplicates"],
            "match_level": sample_stats["match_level"],
            "issues": sample_stats["issues"],
        },
        "weight_check": weight_result,
    }

    _save_check(db, task_id, "overall", overall_status, result)
    new_status = "ready" if overall_status != "fail" else "check_failed"
    task.status = new_status; task.updated_at = _now(); db.commit()

    return ApiResponse(success=True, data=result)


@router.get("/tasks/{task_id}/check-result", response_model=ApiResponse)
def get_check_result(task_id: str, db: Session = Depends(get_db)):
    cr = db.query(CheckResult).filter(
        CheckResult.task_id == task_id,
        CheckResult.check_type == "overall",
    ).order_by(CheckResult.created_at.desc()).first()
    if not cr:
        return ApiResponse(success=False, error="尚未执行检查")
    return ApiResponse(success=True, data=cr.details)


@router.post("/tasks/{task_id}/dimension-mapping", response_model=ApiResponse)
def save_dim_mapping(task_id: str, mappings: list[dict], db: Session = Depends(get_db)):
    _get_task_or_404(task_id, db)
    for m in mappings:
        fm = FieldMapping(
            id=_uid(), task_id=task_id,
            file_type=m.get("file_type",""),
            source_column=m.get("source_column",""),
            target_field=m.get("target_field",""),
            mapping_type="manual",
        )
        db.add(fm)
    db.commit()
    return ApiResponse(success=True, data={"saved": len(mappings)})


# ---- 任务状态 ---------------------------------------------------------------
@router.get("/tasks/{task_id}/status", response_model=ApiResponse)
def task_status(task_id: str, db: Session = Depends(get_db)):
    t = _get_task_or_404(task_id, db)
    return ApiResponse(success=True, data={"status": t.status, "task_id": task_id})


# ---- 分析（占位，阶段3补全）-------------------------------------------------
@router.post("/tasks/{task_id}/analyze", response_model=ApiResponse)
def start_analyze(task_id: str, db: Session = Depends(get_db)):
    task = _get_task_or_404(task_id, db)
    if task.status not in ("ready", "completed", "failed"):
        return ApiResponse(success=False, error=f"当前状态 {task.status} 不允许启动分析，请先完成检查")
    # 阶段3会替换为真正的后台任务
    from ..services.analysis_runner import run_analysis_sync
    import threading
    task.status = "analyzing"; task.updated_at = _now(); db.commit()
    t = threading.Thread(target=run_analysis_sync, args=(task_id,), daemon=True)
    t.start()
    return ApiResponse(success=True, data={"message": "分析已启动", "task_id": task_id})


# ---- 指标（占位）------------------------------------------------------------
@router.get("/tasks/{task_id}/metrics", response_model=ApiResponse)
def get_metrics(task_id: str, db: Session = Depends(get_db)):
    _get_task_or_404(task_id, db)
    results = db.query(MetricResult).filter(MetricResult.task_id == task_id).all()
    overall = next((r.metrics for r in results if r.scope == "overall"), None)
    by_cat  = {r.scope_key: r.metrics for r in results if r.scope == "category"}
    by_dim  = {r.scope_key: r.metrics for r in results if r.scope == "dimension"}
    by_model = {r.scope_key: r.metrics for r in results if r.scope == "model"}
    return ApiResponse(success=True, data={
        "overall": overall,
        "by_category": by_cat,
        "by_dimension": by_dim,
        "by_model": by_model,
    })


# ---- 差异样本（分页）--------------------------------------------------------
@router.get("/tasks/{task_id}/differences", response_model=ApiResponse)
def get_differences(task_id: str, page: int = 1, page_size: int = 20,
                    dimension_code: str = None, severe_only: bool = False,
                    db: Session = Depends(get_db)):
    _get_task_or_404(task_id, db)
    q = db.query(DifferenceRecord).filter(DifferenceRecord.task_id == task_id)
    if dimension_code:
        q = q.filter(DifferenceRecord.dimension_code == dimension_code)
    if severe_only:
        q = q.filter(DifferenceRecord.is_severe_error == True)
    total = q.count()
    items = q.offset((page - 1) * page_size).limit(page_size).all()
    return ApiResponse(success=True, data={
        "total": total, "page": page, "page_size": page_size,
        "items": [_diff_to_dict(r) for r in items],
    })


def _diff_to_dict(r: DifferenceRecord) -> dict:
    extra = r.extra or {}
    gt_exempt   = extra.get("gt_is_exempt", False)
    auto_exempt = extra.get("auto_is_exempt", False)
    has_auto    = extra.get("has_auto", True)
    return {
        "id": r.id, "data_id": r.data_id, "query_id": r.query_id,
        "candidate_model": r.candidate_model, "dimension_code": r.dimension_code,
        "ground_truth_score": "-" if (gt_exempt or r.ground_truth_score is None) else r.ground_truth_score,
        "auto_score": "-" if (auto_exempt or not has_auto or r.auto_score is None) else r.auto_score,
        "delta": r.delta,
        "auto_reason": r.auto_reason,
        "root_cause_category": r.root_cause_category,
        "is_severe_error": r.is_severe_error,
        "gt_is_exempt": gt_exempt,
        "auto_is_exempt": auto_exempt,
        "has_auto": has_auto,
    }


# ---- 优化建议 ---------------------------------------------------------------
@router.get("/tasks/{task_id}/recommendations", response_model=ApiResponse)
def get_recommendations(task_id: str, db: Session = Depends(get_db)):
    _get_task_or_404(task_id, db)
    recs = db.query(Recommendation).filter(Recommendation.task_id == task_id).all()
    def to_dict(r): return {"id":r.id,"rec_type":r.rec_type,"target_dimension":r.target_dimension,
        "category":r.category,"priority":r.priority,"status":r.status,
        "content":r.content,"llm_generated":r.llm_generated}
    return ApiResponse(success=True, data={
        "skill":    [to_dict(r) for r in recs if r.rec_type=="skill"],
        "strategy": [to_dict(r) for r in recs if r.rec_type=="strategy"],
        "weight":   [to_dict(r) for r in recs if r.rec_type=="weight"],
    })


# ---- 权重模拟 ---------------------------------------------------------------
@router.get("/tasks/{task_id}/weight-simulations", response_model=ApiResponse)
def get_weight_simulations(task_id: str, db: Session = Depends(get_db)):
    _get_task_or_404(task_id, db)
    sims = db.query(WeightScenario).filter(WeightScenario.task_id == task_id).all()
    return ApiResponse(success=True, data=[{
        "id":s.id,"scenario_name":s.scenario_name,
        "description":s.description,"weights":s.weights,
        "simulation_result":s.simulation_result,
    } for s in sims])


# ---- 导出报告 ---------------------------------------------------------------
@router.post("/tasks/{task_id}/export", response_model=ApiResponse)
def export_report(task_id: str, db: Session = Depends(get_db)):
    task = _get_task_or_404(task_id, db)
    from ..reports.report_generator import ReportGenerator
    try:
        gen = ReportGenerator(task_id, db)
        path, fname = gen.generate()
        er = ExportedReport(id=_uid(), task_id=task_id, file_name=fname, stored_path=str(path))
        db.add(er); db.commit()
        return ApiResponse(success=True, data={"file_name": fname})
    except Exception as e:
        return ApiResponse(success=False, error=str(e))


@router.get("/tasks/{task_id}/download-report")
def download_report(task_id: str, db: Session = Depends(get_db)):
    er = db.query(ExportedReport).filter(
        ExportedReport.task_id == task_id
    ).order_by(ExportedReport.created_at.desc()).first()
    if not er or not Path(er.stored_path).exists():
        raise HTTPException(404, "报告不存在，请先导出")
    return FileResponse(er.stored_path, filename=er.file_name,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ---- 内部工具 ---------------------------------------------------------------
def _save_check(db: Session, task_id: str, check_type: str, status: str, details: dict):
    cr = CheckResult(id=_uid(), task_id=task_id, check_type=check_type,
                     status=status, details=details, summary={"status": status})
    db.add(cr); db.commit()
