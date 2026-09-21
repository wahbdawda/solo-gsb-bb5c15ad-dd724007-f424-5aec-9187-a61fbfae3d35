# 考古地层关系推演台

基于 **FastAPI + SQLite + 原生 HTML/CSS/JS** 的考古地层（stratigraphy）关系录入与逻辑推演工具。
录入地层单元与单元间的「早于 / 晚于 / 相交」关系后，系统自动：

1. **矛盾环校验** —— 检测时序关系中是否出现逻辑矛盾（循环时序、与"相交"冲突、自反关系）；
2. **层位区间推演** —— 在无矛盾前提下，按所有可行拓扑序计算每个单元的
   **最早可能层位** 与 **最晚可能层位**（自下而上编号，1 = 最早/最深）；
3. **受影响节点标注** —— 新增/删除关系后，高亮共存组、层位区间或矛盾状态发生变化的节点，并给出变化原因；
4. **可视化** —— SVG 关系图（共存组底带、时序箭头、相交虚线、矛盾红边）、层位区间表、可行拓扑序；
5. **JSON 导出** —— 一键导出全部单元、关系及推演结果。

## 关系语义

| 关系 | 含义 | 图论建模 |
| --- | --- | --- |
| A **早于** B | A 叠压/早于 B（A 在 B 下方） | 有向边 A → B |
| A **晚于** B | A 打破/晚于 B | 等价于 B 早于 A，自动归一化为 B → A |
| A **相交** B | 同期共存、无法区分早晚 | 无向、对称、可传递，先收缩为"共存组" |

"相交"按**等价关系**处理：若 A∩B、B∩C，则 A、B、C 属于同一共存组，
在组间有向图上收缩为一个超级节点。若同一共存组内部又出现时序关系
（A 早于 B 等），系统会报告"相交组内时序矛盾"。

### 层位区间算法

对共存组收缩后的有向无环图（DAG）：

- `最早层位(g) = g 的祖先组数 + 1`
- `最晚层位(g) = 共存组总数 − g 的后代组数`
- 最早 = 最晚 ⇒ 该单元在**任何**合法发掘序列中层位唯一（"层位固定"）；
  否则在区间内浮动（例如侧出灰坑与若干主层并列，层位不唯一）。

矛盾时拓扑推演中止，关系图退化为网格布局并把涉冲突关系标红。

## 快速开始（Docker，推荐）

```bash
docker compose up -d --build
```

浏览器打开 <http://localhost:8000> ，点击右上角「载入示例」可立即体验一组
含叠压、打破与相交关系的模拟发掘区数据（10 个单元、10 条关系，其中侧出灰坑 H10 层位浮动）。

数据保存在 Docker 卷 `strata-data`（容器内 `/data/strata.db`），重启不丢失。

## 本地运行（无 Docker）

需要 Python 3.11+：

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
STRATA_DB=./strata.db uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 目录结构

```
.
├── app/
│   ├── main.py        # FastAPI 路由、状态组装、受影响节点 diff、示例数据
│   ├── engine.py      # 纯函数推演核心：并查集收缩、环检测、拓扑序与层位区间
│   ├── database.py    # SQLite 连接、建表、查重
│   └── schemas.py     # Pydantic 入参校验
├── static/
│   ├── index.html     # 单页界面
│   ├── style.css
│   └── app.js         # 关系图（SVG）、表格、冲突面板、受影响高亮
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## HTTP API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/state` | 全量状态：单元、关系、共存组、区间、冲突、拓扑序 |
| POST | `/api/units` | 新增单元 `{code,name,kind,note}` |
| DELETE | `/api/units/{id}` | 删除单元（级联删除相关关系） |
| POST | `/api/relations` | 新增关系 `{source_id,target_id,rel_type,note}` |
| DELETE | `/api/relations/{id}` | 删除关系 |
| POST | `/api/reset/demo` | 载入示例数据 |
| POST | `/api/reset/clear` | 清空所有数据 |
| GET | `/api/export` | 下载完整 JSON（含分析结果） |

所有写操作的响应体与 `/api/state` 结构一致，并额外携带 `affected`：

```json
"affected": [
  {"unit_id": 7, "reasons": ["group_changed", "interval_changed"]}
]
```

原因类型：`new_unit` / `group_changed`（共存组合并）/ `interval_changed`
（层位区间变化）/ `interval_resolved` / `interval_invalid` /
`conflict_introduced`（进入矛盾环）/ `conflict_resolved`。

交互式 API 文档见 <http://localhost:8000/docs>。

## 算法说明

1. 用并查集（DSU）把全部 `intersects` 连通分量收缩成共存组；
2. 时序关系归一化（`later` 翻转方向）后映射为组间有向边；
3. 组内时序边、自反边单独报告；组间图用 DFS 三色标记法找环，回溯栈还原矛盾环；
4. 无环时用 Kahn 算法得到拓扑序，沿拓扑序传播可达闭包，
   据此计算祖先/后代数量与层位区间；
5. 最长前驱链长度作为关系图的垂直分层（rank），较早者绘制在下方，符合考古地层直觉。

## 说明与边界

- 所有计算在每次请求时基于数据库全量重算，数据规模为小型发掘区（数百单元）时无需缓存；
- 环检测针对组级 DAG，同一有向环若经多条回边到达会去重展示；
- "相交"被建模为等价关系（可传递），这是对"同期/共存"的常见简化，
  若需要表达仅两两相交但不可传递的情形，可在 `engine.py` 中调整收缩逻辑。
