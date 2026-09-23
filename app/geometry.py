"""二维几何计算与斯涅尔定律折射。

约定：
- 所有方向向量、法线在内部均归一化。
- 界面为一条直线：由线上一点 point 与指向下一介质的法线 normal 定义。
- 光线沿当前方向前进，只接受前向（t > 0）交点。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

EPS = 1e-12
T_MIN = 1e-9  # 交点参数 t 必须大于该值，避免自相交

# 瞄准求解（aim-solutions）参数
TARGET_DEVIATION_TOL = 1e-6  # 目标偏差收敛阈值（沿观察线切向的有符号距离）
ANGLE_WIDTH_TOL_DEG = 1e-7  # 二分角度区间宽度阈值（度）
MAX_BISECTION_ITERATIONS = 60  # 二分最多迭代次数


def _dot(a: tuple[float, float], b: tuple[float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1]


def normalize(v: tuple[float, float]) -> tuple[float, float]:
    n = math.hypot(v[0], v[1])
    if n < EPS:
        raise ValueError("zero-length vector")
    return (v[0] / n, v[1] / n)


@dataclass
class SegmentResult:
    """一段光线的计算结果。hit_point 为 None 表示光线出射（无后续界面）。"""

    origin: tuple[float, float]
    direction: tuple[float, float]
    n_medium: float
    hit_point: tuple[float, float] | None
    event: str | None  # refraction / total_internal_reflection / no_intersection / None
    n_after: float | None


def _intersect_line(
    origin: tuple[float, float],
    direction: tuple[float, float],
    point: tuple[float, float],
    normal: tuple[float, float],
) -> tuple[float, float] | None:
    """光线与界面直线求交，返回前向交点；平行或交点在身后则返回 None。"""
    denom = _dot(direction, normal)
    if abs(denom) < EPS:
        return None  # 光线与界面平行
    t = _dot((point[0] - origin[0], point[1] - origin[1]), normal) / denom
    if t <= T_MIN:
        return None  # 交点不在前方
    return (origin[0] + t * direction[0], origin[1] + t * direction[1])


def _refract(
    direction: tuple[float, float],
    normal: tuple[float, float],
    n1: float,
    n2: float,
) -> tuple[float, float] | None:
    """按斯涅尔定律计算折射方向；发生全反射时返回 None。

    若光线从法线背面入射，则翻转法线再计算（折射率仍按给定 n1 -> n2）。
    """
    cos_i = _dot(direction, normal)
    if cos_i < 0.0:
        normal = (-normal[0], -normal[1])
        cos_i = -cos_i
    eta = n1 / n2
    sin2_t = eta * eta * max(0.0, 1.0 - cos_i * cos_i)
    if sin2_t > 1.0:
        return None  # 全反射
    cos_t = math.sqrt(1.0 - sin2_t)
    k = cos_t - eta * cos_i
    return (eta * direction[0] + k * normal[0], eta * direction[1] + k * normal[1])


def sample_directions(
    center: tuple[float, float],
    half_angle_deg: float,
    sample_count: int,
) -> list[tuple[float, tuple[float, float]]]:
    """以中心方向为 0°，在 [-a, +a]（度，含端点）等间距生成 sample_count 个方向。

    返回 [(emission_angle_deg, normalized_direction), ...]，角度正向为数学上的
    逆时针方向，端点精确取 -a 与 +a。
    """
    base = normalize(center)
    theta0 = math.atan2(base[1], base[0])
    a = float(half_angle_deg)
    last = sample_count - 1
    result: list[tuple[float, tuple[float, float]]] = []
    for i in range(sample_count):
        if i == 0:
            angle = -a
        elif i == last:
            angle = a
        else:
            angle = -a + 2.0 * a * i / last
        theta = theta0 + math.radians(angle)
        result.append((angle, (math.cos(theta), math.sin(theta))))
    return result


def observation_intersection(
    segments: list[SegmentResult],
    point: tuple[float, float],
    normal: tuple[float, float],
) -> tuple[float, float] | None:
    """取完成追迹后的出射段（最后一段），求其与观察线的前向交点。

    平行（denom≈0）或交点在光线反方向（t<=0）时返回 None。
    """
    final = segments[-1]
    return _intersect_line(final.origin, final.direction, point, normalize(normal))


def observation_tangent(
    normal: tuple[float, float],
) -> tuple[float, float]:
    """观察线单位切向量：法线归一化后逆时针旋转 90°（n=(nx,ny) -> (-ny,nx)）。

    切向沿观察线，目标偏移量即沿该方向的有符号距离。
    """
    nx, ny = normalize(normal)
    return (-ny, nx)


@dataclass
class AimSample:
    """某一发射角的有效评估结果。"""

    angle_deg: float
    direction: tuple[float, float]  # 穿过所有界面后的出射方向
    observation_point: tuple[float, float]  # 出射段与观察线的前向交点
    deviation: float  # 沿观察线切向相对目标点的有符号距离


def solve_aim(
    start: tuple[float, float],
    center_direction: tuple[float, float],
    n_start: float,
    interfaces: list[tuple[tuple[float, float], tuple[float, float], float]],
    observation_point: tuple[float, float],
    observation_normal: tuple[float, float],
    half_angle_deg: float,
    target_offset: float,
    sample_count: int,
) -> list[AimSample]:
    """扫描发射角并二分求穿过目标点的光线。

    目标点 = 观察线给定点 + target_offset * 单位切向量（法线逆时针旋转 90°）。
    目标偏差 = 出射段与观察线前向交点沿切向相对目标点的有符号距离。

    先在 [-half_angle, +half_angle]（度，含端点）等间距采样；仅对**相邻**有效采样
    （追迹 completed 且存在前向观察线交点）偏差异号的区间二分。二分中遇到无效
    追迹或无前向交点则丢弃整个区间，不跨无效采样连根。

    返回按发射角排序、按 1e-7 度去重的解；直接命中（|偏差|<=1e-6）的采样同样返回；
    无解返回空列表。
    """
    base = normalize(center_direction)
    theta0 = math.atan2(base[1], base[0])
    tangent = observation_tangent(observation_normal)
    target = (
        observation_point[0] + target_offset * tangent[0],
        observation_point[1] + target_offset * tangent[1],
    )

    def evaluate(angle: float) -> AimSample | None:
        theta = theta0 + math.radians(angle)
        direction = (math.cos(theta), math.sin(theta))
        segments, status, _reason = trace_ray(start, direction, n_start, interfaces)
        if status != "completed":
            return None
        hit = observation_intersection(segments, observation_point, observation_normal)
        if hit is None:
            return None
        deviation = (
            (hit[0] - target[0]) * tangent[0] + (hit[1] - target[1]) * tangent[1]
        )
        return AimSample(angle, segments[-1].direction, hit, deviation)

    # 等间距扫描；无效采样记 None，使两侧有效采样不构成“相邻”
    grid = [
        evaluate(angle)
        for angle, _d in sample_directions(
            center_direction, half_angle_deg, sample_count
        )
    ]

    solutions: list[AimSample] = []
    for i in range(len(grid) - 1):
        lo, hi = grid[i], grid[i + 1]
        if lo is None or hi is None:
            continue  # 无效采样隔开，不跨无效采样连根
        if abs(lo.deviation) <= TARGET_DEVIATION_TOL:
            solutions.append(lo)
            continue  # 端点已直接命中，该区间不再二分
        if abs(hi.deviation) <= TARGET_DEVIATION_TOL:
            solutions.append(hi)
            continue
        if (lo.deviation < 0.0) == (hi.deviation < 0.0):
            continue  # 偏差同号，无根区间
        mid = _bisect_aim(lo, hi, evaluate)
        if mid is not None:
            solutions.append(mid)

    solutions.sort(key=lambda s: s.angle_deg)

    # 按 1e-7 度去重：相邻解角度差不超过阈值则保留 |偏差| 更小者
    deduped: list[AimSample] = []
    for s in solutions:
        if deduped and s.angle_deg - deduped[-1].angle_deg <= ANGLE_WIDTH_TOL_DEG:
            if abs(s.deviation) < abs(deduped[-1].deviation):
                deduped[-1] = s
        else:
            deduped.append(s)
    return deduped


def _bisect_aim(
    lo: AimSample,
    hi: AimSample,
    evaluate,  # Callable[[float], AimSample | None]
) -> AimSample | None:
    """在偏差异号的相邻有效采样区间上二分。

    停止条件（满足任一）：中点 |偏差|<=1e-6；角度区间宽 <=1e-7 度（取偏差更小的端点）；
    迭代 60 次（兜底取偏差更小的端点）。中点无效（追迹失败或无前向交点）时丢弃整个区间。
    """
    for _ in range(MAX_BISECTION_ITERATIONS):
        if hi.angle_deg - lo.angle_deg <= ANGLE_WIDTH_TOL_DEG:
            return lo if abs(lo.deviation) <= abs(hi.deviation) else hi
        mid_angle = 0.5 * (lo.angle_deg + hi.angle_deg)
        mid = evaluate(mid_angle)
        if mid is None:
            return None  # 中点无效：丢弃该区间，不跨无效采样连根
        if abs(mid.deviation) <= TARGET_DEVIATION_TOL:
            return mid
        if (lo.deviation < 0.0) == (mid.deviation < 0.0):
            lo = mid
        else:
            hi = mid
    return lo if abs(lo.deviation) <= abs(hi.deviation) else hi


def centroid_and_rms(
    points: list[tuple[float, float]],
) -> tuple[tuple[float, float], float] | None:
    """点集质心与 RMS 半径（各点到质心距离平方均值的开方）；空集返回 None。"""
    count = len(points)
    if count == 0:
        return None
    cx = sum(p[0] for p in points) / count
    cy = sum(p[1] for p in points) / count
    mean_sq = sum((p[0] - cx) ** 2 + (p[1] - cy) ** 2 for p in points) / count
    return (cx, cy), math.sqrt(mean_sq)


def trace_ray(
    start: tuple[float, float],
    direction: tuple[float, float],
    n_start: float,
    interfaces: list[tuple[tuple[float, float], tuple[float, float], float]],
) -> tuple[list[SegmentResult], str, str | None]:
    """依次对每个界面做前向求交并折射。

    interfaces: 按顺序排列的 (point, normal, n_next)。
    返回 (segments, status, reason)，status ∈
    completed / total_internal_reflection / no_intersection。
    """
    origin = (float(start[0]), float(start[1]))
    d = normalize(direction)
    n_current = float(n_start)
    segments: list[SegmentResult] = []

    for idx, (point, normal, n_next) in enumerate(interfaces):
        nrm = normalize(normal)
        hit = _intersect_line(origin, d, point, nrm)
        if hit is None:
            reason = (
                f"光线与第 {idx} 个界面平行，或交点位于光线反方向，追迹停止"
            )
            segments.append(SegmentResult(origin, d, n_current, None, "no_intersection", None))
            return segments, "no_intersection", reason

        new_dir = _refract(d, nrm, n_current, n_next)
        if new_dir is None:
            reason = (
                f"在第 {idx} 个界面发生全反射：n1={n_current} -> n2={n_next}，"
                f"入射角超过临界角，追迹停止"
            )
            segments.append(
                SegmentResult(origin, d, n_current, hit, "total_internal_reflection", n_next)
            )
            return segments, "total_internal_reflection", reason

        segments.append(SegmentResult(origin, d, n_current, hit, "refraction", n_next))
        origin = hit
        d = new_dir
        n_current = n_next

    # 穿过所有界面，最后一段出射
    segments.append(SegmentResult(origin, d, n_current, None, None, None))
    return segments, "completed", None
