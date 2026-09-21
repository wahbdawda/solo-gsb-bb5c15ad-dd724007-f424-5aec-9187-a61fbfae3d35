"""推演引擎冒烟测试：直接 python tests/test_engine.py 运行。"""
import os
import sys
from pathlib import Path

os.environ.setdefault("STRATA_DB", "/tmp/strata_test.db")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.engine import analyze, INTERSECTS, EARLIER, LATER


def U(ids):
    return [{"id": i, "code": f"U{i}"} for i in ids]


def R(rid, a, b, t):
    return {"id": rid, "source_id": a, "target_id": b, "rel_type": t}


def iv(res, uid):
    u = res["units"][uid]
    return (u["earliest"], u["latest"])


# 1. 空数据
r = analyze([], [])
assert r["consistent"] and r["groups"] == []

# 2. 单链 A<B<C<D：全部层位固定
r = analyze(U([1, 2, 3, 4]), [R(1, 1, 2, EARLIER), R(2, 2, 3, EARLIER), R(3, 3, 4, EARLIER)])
assert r["consistent"]
assert iv(r, 1) == (1, 1) and iv(r, 4) == (4, 4)
assert r["topo_order"] == [1, 2, 3, 4]

# 3. later 归一化：1 later 3 <=> 3 earlier 1
r = analyze(U([1, 3]), [R(1, 1, 3, LATER)])
edge = r["edges"][0]
assert (edge["from_group"], edge["to_group"]) == (2, 1)

# 4. 三支汇入：1->3, 1->4, 3->4：1,3,4 全部层位固定
units = U([1, 3, 4])
r = analyze(units, [R(1, 1, 3, EARLIER), R(2, 1, 4, EARLIER), R(3, 3, 4, EARLIER)])
assert iv(r, 1) == (1, 1)
assert iv(r, 3) == (2, 2)
assert iv(r, 4) == (3, 3)

# 5. 真正的浮动支：1->2, 1->3（2 和 3 互不约束）
units = U([1, 2, 3])
r = analyze(units, [R(1, 1, 2, EARLIER), R(2, 1, 3, EARLIER)])
assert iv(r, 2) == (2, 3) and iv(r, 3) == (2, 3)
assert iv(r, 1) == (1, 1)
assert r["implied_pairs"] == 0  # 2 条显式边，2 对可达，无传递隐含

# 6. 传递隐含：1->2->3 同时 1->3 显式 => implied 0；删除 1->3 后 implied 1
units = U([1, 2, 3])
r = analyze(units, [R(1, 1, 2, EARLIER), R(2, 2, 3, EARLIER)])
assert r["implied_pairs"] == 1
r = analyze(units, [R(1, 1, 2, EARLIER), R(2, 2, 3, EARLIER), R(3, 1, 3, EARLIER)])
assert r["implied_pairs"] == 0

# 7. 相交收缩：1∩2，2->3，1->3
units = U([1, 2, 3])
r = analyze(units, [R(1, 1, 2, INTERSECTS), R(2, 2, 3, EARLIER)])
assert r["consistent"]
assert len(r["groups"]) == 2
g1 = r["groups"][0]
assert g1["unit_ids"] == [1, 2]
assert iv(r, 1) == (1, 1) and iv(r, 2) == (1, 1)
assert iv(r, 3) == (2, 2)

# 8. 跨环相交矛盾：1早于2，2早于3，1∩3 => 1,3 同组，2->组 与 组->2 成环
units = U([1, 2, 3])
r = analyze(units, [R(1, 1, 2, EARLIER), R(2, 2, 3, EARLIER), R(3, 1, 3, INTERSECTS)])
assert not r["consistent"]
assert r["intervals_available"] is False
assert len(r["conflicts"]) == 1
assert r["conflicts"][0]["kind"] == "cycle"
assert set(r["conflict_unit_ids"]) == {1, 2, 3}

# 9. 组内时序矛盾：1∩2 且 1 早于 2
units = U([1, 2])
r = analyze(units, [R(1, 1, 2, INTERSECTS), R(2, 1, 2, EARLIER)])
assert not r["consistent"]
assert r["conflicts"][0]["kind"] == "intra_intersects"
assert set(r["conflicts"][0]["relation_ids"]) == {2}

# 10. 自反关系
r = analyze(U([1]), [R(1, 1, 1, EARLIER)])
assert not r["consistent"]
assert r["conflicts"][0]["kind"] == "self_loop"

# 11. 普通三角环：1->2->3->1
units = U([1, 2, 3])
r = analyze(units, [R(1, 1, 2, EARLIER), R(2, 2, 3, EARLIER), R(3, 3, 1, EARLIER)])
assert not r["consistent"]
assert r["conflicts"][0]["kind"] == "cycle"
assert set(r["conflicts"][0]["relation_ids"]) == {1, 2, 3}
assert r["topo_order"] == []

# 12. 演示数据集规模
from app.main import DEMO_UNITS, DEMO_RELATIONS  # noqa: E402
code2id = {c: i + 1 for i, (c, *_rest) in enumerate(DEMO_UNITS)}
du = [{"id": code2id[c], "code": c} for c, *_ in DEMO_UNITS]
dr = []
for i, (a, b, t) in enumerate(DEMO_RELATIONS, start=1):
    dr.append(R(i, code2id[a], code2id[b], t))
r = analyze(du, dr)
assert r["consistent"], [c["message"] for c in r["conflicts"]]
assert len(r["groups"]) == 8  # 10 单元：L5∩H9、F7∩Z8 两次合并
# G1{L5,H9} 位于 1；M6 固定 2；F7/Z8 固定 3；L4 固定 4
assert iv(r, code2id["L5"]) == (1, 1)
assert iv(r, code2id["H9"]) == (1, 1)
assert iv(r, code2id["M6"]) == (2, 2)
assert iv(r, code2id["F7"]) == (3, 3)
assert iv(r, code2id["Z8"]) == (3, 3)
assert iv(r, code2id["L4"]) == (4, 4)
# 侧支 H10：祖先只有 L4，可在 L3/L2/L1 任一层并列甚至最后
assert iv(r, code2id["H10"]) == (5, 8)
# L1 因 H10 浮动而可与它并列，自身区间 [7,8]
assert iv(r, code2id["L1"]) == (7, 8)
# F7/Z8 同组同区间
assert iv(r, code2id["F7"]) == iv(r, code2id["Z8"])
print("engine tests: all 12 passed")
