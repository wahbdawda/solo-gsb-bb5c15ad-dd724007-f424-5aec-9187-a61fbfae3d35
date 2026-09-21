# 考古地层关系推演台

一个用于考古地层（stratigraphy）关系录入与逻辑推演的小型 Web 应用。
基于 **Python FastAPI + SQLite + 原生前端（HTML/CSS/SVG/JS）**，无需 Node、无需构建步骤，
一条 `docker compose up` 即可在浏览器中使用。

![stack](https://img.shields.io/badge/stack-FastAPI%20%7C%20SQLite%20%7C%20vanilla%20JS-8a5a2b)

## 功能

- **地层单元录入**：编号、名称、备注；支持编辑、删除（删除单元级联清理其关系）。
- **三种关系**：
  - `早于`（A 的形成早于 B，对应 Harris 矩阵中的 A → B）
  - `晚于`（自动等价于反向“早于”）
  - `相交`（同期共存/打破而不可定先后，作为无向关系处理）
- **矛盾环校验**，自动检出两类逻辑冲突并在图中标红：
  1. 两个被声明为“相交（同期）”的单元之间又存在早晚关系；
  2. 早晚关系在共存组之间形成有向环（A 早于 B、B 早于 C、C 又早于 A……），
     基于 Tarjan 强连通分量算法定位，并给出具体环路径。
- **层位区间推演**：无冲突时，把“相交”单元并查集（DSU）合并为共存组（共 M 个堆积单位），
  对共存组时序 DAG 求传递闭包，得到该组在**全部可行拓扑序中的位置区间**：
  - 每个单元的 **最早可能层位** = 必须先于它的组数（前驱闭包大小）+ 1；
  - **最晚可能层位** = M − 必须晚于它的组数（后继闭包大小）。

  因此输出的 `[最早–最晚]` 区间覆盖该单元在所有可行拓扑序中可能占据的位置；
  区间固定（最早=最晚）表示该单元在任何合法顺序中层位唯一。
  注意位置上下界由**必须先/后于它的堆积单位个数**决定，而不是最长链长度：
  一个单元若领先两个互不可比的后继，二者都会把它的最晚位置向前压。
- **受影响节点标记**：新增/删除关系或删除单元后，凡是“共存组成员、层位区间、冲突状态”
  发生变化的单元都会以橙色描边标出，关系两端必标。
- **关系图**：SVG 分层绘制（最早层位在底部，契合地层剖面习惯），相交组以虚线框聚合，
  矛盾关系红色加粗、普通早晚关系带方向箭头；冲突时切换为网格布局以便看清环。
- **冲突详情面板**：逐条说明矛盾原因与涉及单元，点击可定位节点。
- **JSON 导出**：一键下载包含全部单元、关系与推演结果（区间、冲突、共存组）的 JSON。

## 目录结构

```
.
├── app/
│   ├── main.py          # FastAPI 路由（单元/关系 CRUD、导出、示例数据）
│   ├── logic.py         # 关系归一化、DSU、Tarjan 环检测、层位区间推演、受影响比对
│   ├── db.py            # SQLite 连接与建表
│   ├── schemas.py       # Pydantic 请求模型与校验
│   ├── seed.py          # 内置示例（7 个单元的 Harris 式地层）
│   └── static/          # 轻量前端 index.html / styles.css / app.js
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## 快速开始（Docker）

```bash
docker compose up --build
```

启动后浏览器打开：

- 应用界面：<http://localhost:8000/>
- OpenAPI 文档：<http://localhost:8000/docs>
- 健康检查：<http://localhost:8000/health>

SQLite 数据文件持久化在命名卷 `strata-data`（容器内 `/data/strata.db`），
容器重建不丢数据；也可在 compose 中改为绑定本地目录。

## 本地运行（不使用 Docker）

需要 Python 3.11+：

```bash
python -m venv .venv
source .venv/bin/          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export STRATA_DB_PATH=./strata.db   # Windows PowerShell: $env:STRATA_DB_PATH="./strata.db"
uvicorn app.main:app --reload --port 8000
```

打开 <http://localhost:8000/>，点击右上角 **“载入示例”** 即可看到一份
包含“生土层—房基/垫土（相交同期）—灰坑—文化层—墓葬—耕土”的演示数据。

## 使用说明

1. 在左栏添加地层单元（编号唯一，如 `U1`、`H2`）。
2. 在右栏选择两个单元与关系类型（A **早于/晚于/相交** B）并添加。
3. 中间图实时重绘；无冲突时每个节点下方显示其可行层位区间，
   底部文字给出总层位数与共存组统计。
4. 故意制造矛盾（例如再添加“U7 早于 U1”）即可看到冲突详情、红色环边
   与受影响节点高亮；删除标红关系后推演自动恢复。
5. 点击单元可在列表与图中联动定位；点击冲突条目可跳转到涉及节点。
6. 点击 **导出 JSON** 下载完整快照。

## REST API 摘要

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/state` | 全部单元、关系、推演结果与受影响列表 |
| POST | `/api/units` | 新增单元 `{id,name,note}` |
| PATCH | `/api/units/{id}` | 修改单元名称/备注 |
| DELETE | `/api/units/{id}` | 删除单元（级联删除关联关系） |
| POST | `/api/relations` | 新增关系 `{kind,source_id,target_id,note}` |
| DELETE | `/api/relations/{id}` | 删除关系 |
| POST | `/api/sample` | 清空并载入示例数据 |
| POST | `/api/reset` | 清空全部数据 |
| GET | `/api/export` | 下载 JSON 快照 |

`kind` 取值：`earlier_than` / `later_than` / `intersects`。

### 导出 JSON 结构（节选）

```json
{
  "exported_at": "2026-09-21T08:00:00+00:00",
  "units": [{ "id": "U4", "name": "灰坑 H1", "note": "..." }],
  "relations": [{ "id": 4, "kind": "earlier_than", "source_id": "U2", "target_id": "U4" }],
  "analysis": {
    "has_conflict": false,
    "conflicts": [],
    "components": [{ "id": "U2", "members": ["U2", "U3"], "level": 2 }],
    "total_levels": 6,
    "intervals": { "U4": { "earliest": 3, "latest": 3 } }
  }
}
```

## 测试

```bash
# 前端渲染冒烟测试（仅需 Node，无浏览器依赖）
node tests/smoke_frontend.js
```

后端推演逻辑可用一段内置的暴力校验脚本验证（枚举全部拓扑序比对区间），
核心入口为 `app.logic.analyze(state)`，输入 `{"units": [...], "relations": [...]}`。

## 设计说明与边界

- **相交**按 Harris 矩阵惯例解释为“同期/无法定序”的等价关系：
  相交关系传递并合并（U2 相交 U3、U3 相交 U4 视为三者同组），
  组内成员共享同一可行层位区间。若实际材料中“相交”仅表示局部打破、
  不应传递，可在 `app/logic.py` 中调整 DSU 合并策略。
- 矛盾状态下系统**保留全部数据**，不会拒绝录入——关系照常保存并标红，
  待用户删除冲突关系后区间推演自动恢复，便于对比和教学演示。
- 层位区间针对的是“全部可行拓扑序”的精确上下界（DAG 最长路径，Kahn 算法），
  而非单一任意排序。
- 并发写入由进程内锁串行化；SQLite 开启 WAL，适合单机/课堂规模使用。
