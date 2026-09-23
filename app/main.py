"""二维介质光线追迹 API。

POST /api/traces                      提交光线与界面序列，返回追迹结果并保存
GET  /api/traces                      列出所有已保存的追迹（摘要）
GET  /api/traces/{trace_id}           按编号查询完整追迹（含各段交点与方向）
GET  /api/traces/{trace_id}/segments/{seg_index}  按编号查询某一段
POST /api/beam-evaluations            以中心方向为轴对称采样多条光线，返回每条光线
                                      的发射角、追迹状态、观察线交点及质心/RMS 半径
POST /api/aim-solutions               扫描发射角并二分求穿过观察线上目标点的解
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from . import db
from .geometry import (
    centroid_and_rms,
    observation_intersection,
    observation_tangent,
    sample_directions,
    solve_aim,
    trace_ray,
)
from .schemas import (
    AimRequest,
    AimSolutionsOut,
    BeamEvaluationOut,
    BeamRequest,
    SegmentOut,
    TraceOut,
    TraceRequest,
    TraceSummary,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()  # 启动时建库建表
    yield


app = FastAPI(
    title="2D Medium Ray Tracing API",
    version="1.0.0",
    description="二维介质光线追迹：按斯涅尔定律折射，遇全反射停止并返回原因。",
    lifespan=lifespan,
)


@app.get("/")
def root() -> dict:
    return {"service": "2d-ray-tracing", "docs": "/docs", "api": "/api/traces"}


@app.post("/api/traces", response_model=TraceOut, status_code=201)
def create_trace(req: TraceRequest) -> dict:
    interfaces = [
        (itf.point.as_tuple(), itf.normal.as_tuple(), itf.n_next)
        for itf in req.interfaces
    ]
    segments, status, reason = trace_ray(
        req.start.as_tuple(), req.direction.as_tuple(), req.n_start, interfaces
    )
    trace_id = db.insert_trace(
        req.start.as_tuple(),
        req.direction.as_tuple(),
        req.n_start,
        status,
        reason,
        segments,
    )
    return db.get_trace(trace_id)


@app.get("/api/traces", response_model=list[TraceSummary])
def list_traces() -> list[dict]:
    return db.list_traces()


@app.get("/api/traces/{trace_id}", response_model=TraceOut)
def get_trace(trace_id: int) -> dict:
    trace = db.get_trace(trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail=f"追迹 {trace_id} 不存在")
    return trace


@app.get("/api/traces/{trace_id}/segments/{seg_index}", response_model=SegmentOut)
def get_segment(trace_id: int, seg_index: int) -> dict:
    segment = db.get_segment(trace_id, seg_index)
    if segment is None:
        raise HTTPException(
            status_code=404, detail=f"追迹 {trace_id} 的第 {seg_index} 段不存在"
        )
    return segment


@app.post("/api/beam-evaluations", response_model=BeamEvaluationOut)
def evaluate_beam(req: BeamRequest) -> dict:
    """以中心方向为 0° 在 [-a, +a] 内等间距旋转采样，逐条追迹并评估观察线光斑。

    仅对追迹完成（status=completed）且与观察线存在前向交点的光线纳入统计；
    未完成、与观察线平行或交点在光线反方向时 observation_point 为 null。
    """
    interfaces = [
        (itf.point.as_tuple(), itf.normal.as_tuple(), itf.n_next)
        for itf in req.interfaces
    ]
    start = req.start.as_tuple()

    rays_out: list[dict] = []
    hit_points: list[tuple[float, float]] = []
    for angle, direction in sample_directions(
        req.center_direction.as_tuple(), req.half_angle_deg, req.sample_count
    ):
        segments, status, reason = trace_ray(
            start, direction, req.n_start, interfaces
        )
        observation_point = None
        if status == "completed":
            observation_point = observation_intersection(
                segments,
                req.observation_line.point.as_tuple(),
                req.observation_line.normal.as_tuple(),
            )
            if observation_point is not None:
                hit_points.append(observation_point)
        rays_out.append(
            {
                "emission_angle_deg": angle,
                "direction": {"x": direction[0], "y": direction[1]},
                "status": status,
                "reason": reason,
                "observation_point": (
                    None
                    if observation_point is None
                    else {"x": observation_point[0], "y": observation_point[1]}
                ),
            }
        )

    stats = centroid_and_rms(hit_points)
    return {
        "half_angle_deg": req.half_angle_deg,
        "sample_count": req.sample_count,
        "ray_count": len(rays_out),
        "hit_count": len(hit_points),
        "centroid": None if stats is None else {"x": stats[0][0], "y": stats[0][1]},
        "rms_radius": None if stats is None else stats[1],
        "rays": rays_out,
    }


@app.post("/api/aim-solutions", response_model=AimSolutionsOut)
def solve_aim_solutions(req: AimRequest) -> dict:
    """在半角范围内扫描发射角，二分求穿过观察线上目标点的光线。

    目标点沿观察线切向量（法线逆时针旋转 90°）由给定点偏移 target_offset 得到。
    等间距扫描后仅对相邻有效采样目标偏差异号的区间二分；二分中遇无效追迹或无前向
    交点则丢弃该区间，不跨无效采样连根。返回按角度排序、按 1e-7 度去重的解；
    采样点直接命中（|偏差|<=1e-6）也返回；无解返回空列表。即时计算，不入库。
    """
    interfaces = [
        (itf.point.as_tuple(), itf.normal.as_tuple(), itf.n_next)
        for itf in req.interfaces
    ]
    obs_point = req.observation_line.point.as_tuple()
    obs_normal = req.observation_line.normal.as_tuple()

    solutions = solve_aim(
        req.start.as_tuple(),
        req.center_direction.as_tuple(),
        req.n_start,
        interfaces,
        obs_point,
        obs_normal,
        req.half_angle_deg,
        req.target_offset,
        req.sample_count,
    )

    tangent = observation_tangent(obs_normal)
    target_point = (
        obs_point[0] + req.target_offset * tangent[0],
        obs_point[1] + req.target_offset * tangent[1],
    )
    return {
        "half_angle_deg": req.half_angle_deg,
        "sample_count": req.sample_count,
        "target_offset": req.target_offset,
        "target_point": {"x": target_point[0], "y": target_point[1]},
        "solution_count": len(solutions),
        "solutions": [
            {
                "emission_angle_deg": s.angle_deg,
                "direction": {"x": s.direction[0], "y": s.direction[1]},
                "observation_point": {
                    "x": s.observation_point[0],
                    "y": s.observation_point[1],
                },
                "target_deviation": s.deviation,
            }
            for s in solutions
        ],
    }
