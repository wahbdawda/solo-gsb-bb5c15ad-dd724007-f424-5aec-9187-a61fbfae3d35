"""API 端到端测试：启动后模拟浏览器侧的完整操作流。"""
import os
import sys
from pathlib import Path

os.environ["STRATA_DB"] = "/tmp/strata_api_test.db"
if os.path.exists("/tmp/strata_api_test.db"):
    os.remove("/tmp/strata_api_test.db")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

c = TestClient(app)

# 空状态
s = c.get("/api/state").json()
assert s["consistent"] and s["units"] == []

# 示例数据
s = c.post("/api/reset/demo").json()
assert s["consistent"], s["conflicts"]
assert len(s["units"]) == 10 and len(s["relations"]) == 10
assert len(s["groups"]) == 8
assert s["implied_pairs"] >= 1

# 新增单元
s = c.post("/api/units", json={"code": "W2", "name": "墙基", "kind": "wall"}).json()
wid = s["units"][-1]["id"]
assert s["affected"] == [{"unit_id": wid, "reasons": ["new_unit"]}]

# 重复编号 409
r = c.post("/api/units", json={"code": "W2", "kind": "wall"})
assert r.status_code == 409

# 非法类型 422
r = c.post("/api/units", json={"code": "X", "kind": "bogus"})
assert r.status_code == 422

# 空白编号 422
r = c.post("/api/units", json={"code": "   "})
assert r.status_code == 422

# 建立关系 L1 早于 W2（链尾挂新单元）：W2 由孤立区间 [1,9] 收紧为 [8,9]
l1 = next(u for u in s["units"] if u["code"] == "L1")
s = c.post(
    "/api/relations",
    json={"source_id": l1["id"], "target_id": wid, "rel_type": "earlier"},
).json()
w2 = next(u for u in s["units"] if u["id"] == wid)
assert (w2["earliest"], w2["latest"]) == (8, 9)
# W2 收紧；此前孤立的 W2 曾使链上各单元 latest 扩张 1 位，加边后一并回收
aff = {a["unit_id"]: a["reasons"] for a in s["affected"]}
assert "interval_changed" in aff[wid]
assert "interval_changed" in aff[l1["id"]]

# 等价关系查重：W2 later L1 与 L1 earlier W2 等价 -> 409
r = c.post(
    "/api/relations",
    json={"source_id": wid, "target_id": l1["id"], "rel_type": "later"},
)
assert r.status_code == 409

# 相交对称性查重
l5 = next(u for u in s["units"] if u["code"] == "L5")
h9 = next(u for u in s["units"] if u["code"] == "H9")
r = c.post(
    "/api/relations",
    json={"source_id": h9["id"], "target_id": l5["id"], "rel_type": "intersects"},
)
assert r.status_code == 409

# 自反关系 400
r = c.post(
    "/api/relations",
    json={"source_id": wid, "target_id": wid, "rel_type": "earlier"},
)
assert r.status_code == 400

# 制造矛盾环：W2 早于 L5（链尾 -> 链头）
s = c.post(
    "/api/relations",
    json={"source_id": wid, "target_id": l5["id"], "rel_type": "earlier"},
).json()
assert not s["consistent"]
assert s["conflicts"][0]["kind"] == "cycle"
assert set(s["conflict_unit_ids"]) == set(s["conflicts"][0]["unit_ids"])
assert wid in s["conflict_unit_ids"] and l5["id"] in s["conflict_unit_ids"]
# 受影响节点应标记 conflict_introduced
aff = {a["unit_id"]: a["reasons"] for a in s["affected"]}
assert "conflict_introduced" in aff[wid]
# 区间失效
assert s["intervals_available"] is False

# 删除该矛盾关系后恢复
rid = s["new_relation_id"]
s = c.delete(f"/api/relations/{rid}").json()
assert s["consistent"], s["conflicts"]
assert s["intervals_available"] is True
aff = {a["unit_id"]: a["reasons"] for a in s["affected"]}
assert "conflict_resolved" in aff[wid]

# 删除单元级联：删掉 W2 后其关系一起消失
s = c.delete(f"/api/units/{wid}").json()
assert all(u["id"] != wid for u in s["units"])
assert all(
    wid not in (r["source_id"], r["target_id"]) for r in s["relations"]
)

# 导出 JSON 结构
exp = c.get("/api/export").json()
assert exp["tool"] == "archaeo-stratigraphy-console"
assert exp["analysis"]["consistent"] is True
assert "exported_at" in exp and len(exp["units"]) == 10

# 清空
s = c.post("/api/reset/clear").json()
assert s["units"] == [] and s["relations"] == [] and s["groups"] == []

# 静态页面
r = c.get("/")
assert r.status_code == 200 and r.url.path == "/static/index.html"
r = c.get("/static/app.js")
assert r.status_code == 200

print("api tests: all passed")
