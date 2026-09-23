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
