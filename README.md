# 2D 介质光线追迹 API

基于 **Python + FastAPI + SQLite** 的二维光线追迹服务：提交初始光线（起点、方向）、起始介质折射率，以及按顺序排列的界面（界面上一点、指向下一介质的法线、下一介质折射率），服务逐界面计算前向交点并依斯涅尔定律更新方向；遇到全反射（或光线与界面平行 / 交点在反方向）即停止并返回原因。追迹结果保存到 SQLite，可按编号查询各段交点与方向。

## 启动

```bash
docker compose up --build
```

启动时会安装依赖并自动建库建表（SQLite 文件存于命名卷 `raytrace-data` 中）。

- **API 地址**：http://localhost:8000
- **交互式文档（Swagger UI）**：http://localhost:8000/docs
- **端口**：`8000`

本地开发（不用 Docker）：

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## API 一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/traces` | 提交光线与界面序列，执行追迹、保存并返回完整结果 |
| GET | `/api/traces` | 列出所有已保存追迹的摘要 |
| GET | `/api/traces/{trace_id}` | 按编号查询完整追迹（含各段交点与方向） |
| GET | `/api/traces/{trace_id}/segments/{seg_index}` | 按编号查询某一段的交点与方向 |
| POST | `/api/beam-evaluations` | 扇形采样多条光线逐条追迹，返回各光线发射角、状态、观察线交点及质心/RMS（不入库） |

### 请求示例

```bash
curl -X POST http://localhost:8000/api/traces \
  -H "Content-Type: application/json" \
  -d '{
    "start": {"x": 0, "y": 0},
    "direction": {"x": 1, "y": 0.5},
    "n_start": 1.0,
    "interfaces": [
      {"point": {"x": 2, "y": 0}, "normal": {"x": 1, "y": 0}, "n_next": 1.5},
      {"point": {"x": 4, "y": 0}, "normal": {"x": 1, "y": 0}, "n_next": 1.0}
    ]
  }'
```

### 响应说明

- `status`：`completed`（穿过所有界面）、`total_internal_reflection`（全反射停止）、`no_intersection`（与界面平行或交点在反方向）
- `reason`：停止原因（完成时为 `null`）
- `segments[]`：每段包含 `origin`（段起点）、`direction`（段方向）、`n_medium`（所在介质折射率）、`hit_point`（与下一界面的交点，出射段为 `null`）、`event`（`refraction` / `total_internal_reflection` / `no_intersection` / `null`）

### 全反射示例

```bash
curl -X POST http://localhost:8000/api/traces \
  -H "Content-Type: application/json" \
  -d '{
    "start": {"x": 0, "y": 0},
    "direction": {"x": 1, "y": 2},
    "n_start": 1.5,
    "interfaces": [
      {"point": {"x": 2, "y": 0}, "normal": {"x": 1, "y": 0}, "n_next": 1.0}
    ]
  }'
# status = "total_internal_reflection"，reason 说明入射角超过临界角
```

## 光束评估

`POST /api/beam-evaluations` 以中心方向为 0°，在对称半角 `[-half_angle_deg, +half_angle_deg]`（度，要求 `0 < a < 90`）内**含端点等间距**旋转生成 `sample_count`（2～101）条光线，逐条复用同一套追迹逻辑穿过给定的顺序界面，并在追迹完成后取最终出射段与**观察线**求前向交点。该接口为即时计算，结果不写入数据库。

- 发射角正方向为数学上的**逆时针**方向，端点光线的发射角精确为 `-a` 与 `+a`。
- 仅当追迹状态为 `completed` 且出射段与观察线存在**前向**交点时返回交点；追迹未完成（全反射 / 中途无交点）、与观察线平行或交点位于光线反方向时 `observation_point` 为 `null`。
- `centroid` / `rms_radius` 只统计非空交点：质心为交点坐标均值，RMS 半径为各交点到质心距离平方均值的开方；没有任何命中时二者均为 `null`。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/beam-evaluations` | 光束扇形采样、逐条追迹并评估观察线上的光斑（质心与 RMS 半径） |

### 光束评估请求示例

```bash
curl -X POST http://localhost:8000/api/beam-evaluations \
  -H "Content-Type: application/json" \
  -d '{
    "start": {"x": 0, "y": 0},
    "center_direction": {"x": 1, "y": 0},
    "half_angle_deg": 10,
    "sample_count": 21,
    "n_start": 1.0,
    "interfaces": [
      {"point": {"x": 2, "y": 0}, "normal": {"x": 1, "y": 0}, "n_next": 1.5},
      {"point": {"x": 4, "y": 0}, "normal": {"x": 1, "y": 0}, "n_next": 1.0}
    ],
    "observation_line": {"point": {"x": 10, "y": 0}, "normal": {"x": 1, "y": 0}}
  }'
```

### 光束评估响应说明

```json
{
  "half_angle_deg": 10.0,
  "sample_count": 21,
  "ray_count": 21,
  "hit_count": 21,
  "centroid": {"x": 10.0, "y": 0.0},
  "rms_radius": 0.9922,
  "rays": [
    {
      "emission_angle_deg": -10.0,
      "direction": {"x": 0.9848, "y": -0.1736},
      "status": "completed",
      "reason": null,
      "observation_point": {"x": 10.0, "y": -0.9922}
    }
  ]
}
```

- `ray_count`：实际追迹的光线数（等于 `sample_count`）；`hit_count`：观察线上存在有效前向交点的光线数。
- `rays[]` 按发射角从 `-a` 到 `+a` 排列，每条含 `emission_angle_deg`（相对中心方向的发射角，度）、`direction`（归一化后的实际发射方向）、`status` / `reason`（复用单光线追迹的状态与停止原因）、`observation_point`（观察线前向交点，无效时为 `null`）。
- 无任何命中时：`hit_count` 为 0，`centroid` 与 `rms_radius` 均为 `null`。

## 项目结构

```
app/
  main.py       FastAPI 路由与生命周期（启动时建库）
  geometry.py   二维求交、斯涅尔折射、方向采样与光斑质心/RMS 计算
  db.py         SQLite 持久化（traces / segments 两表）
  schemas.py    Pydantic 请求 / 响应模型
Dockerfile
docker-compose.yml
requirements.txt
```
