"""FastAPI 应用：考古地层关系推演台。"""

from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import engine
from .database import (
    find_relation,
    get_db,
    init_db,
    list_relations,
    list_units,
)
from .schemas import RelationIn, UnitIn

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = PROJECT_ROOT / "static"

app = FastAPI(title="考古地层关系推演台", version="1.0.0")


# --------------------------------------------------------------------------- #
# 状态组装
# --------------------------------------------------------------------------- #
def _unit_snapshot(analysis: dict) -> dict:
    groups_by_id = {g["id"]: g for g in analysis["groups"]}
    snap: dict[int, dict] = {}
    for uid, a in analysis["units"].items():
        gid = a["group_id"]
        snap[uid] = {
            "members": tuple(groups_by_id[gid]["unit_ids"]),
            "earliest": a.get("earliest"),
            "latest": a.get("latest"),
            "conflicted": a["conflicted"],
        }
    return snap


def _diff_snapshots(before: dict, after: dict) -> list[dict]:
    """对比新增关系前后每个单元的推演结果，返回受影响节点及原因。"""
    affected = []
    for uid, new in after.items():
        old = before.get(uid)
        if old is None:
            affected.append({"unit_id": uid, "reasons": ["new_unit"]})
            continue
        reasons = []
        if old["members"] != new["members"]:
            reasons.append("group_changed")
        if old["earliest"] != new["earliest"] or old["latest"] != new["latest"]:
            if old["earliest"] is None:
                reasons.append("interval_resolved")
            elif new["earliest"] is None:
                reasons.append("interval_invalid")
            else:
                reasons.append("interval_changed")
        if old["conflicted"] != new["conflicted"]:
            reasons.append(
                "conflict_resolved" if old["conflicted"] else "conflict_introduced"
            )
        if reasons:
            affected.append({"unit_id": uid, "reasons": reasons})
    return sorted(affected, key=lambda x: x["unit_id"])


REASON_LABELS = {
    "new_unit": "新录入单元",
    "group_changed": "共存组变化（相交关系合并）",
    "interval_changed": "最早/最晚层位区间变化",
    "interval_resolved": "矛盾解除，区间可计算",
    "interval_invalid": "引入矛盾，区间失效",
    "conflict_resolved": "脱离矛盾环",
    "conflict_introduced": "进入矛盾环",
}


def build_state(conn) -> dict:
    units = list_units(conn)
    relations = list_relations(conn)
    analysis = engine.analyze(units, relations)

    groups_by_id = {g["id"]: g for g in analysis["groups"]}
    units_out = []
    for u in units:
        a = analysis["units"][u["id"]]
        item = dict(u)
        item.update(
            group_id=a["group_id"],
            conflicted=a["conflicted"],
            group_members=list(groups_by_id[a["group_id"]]["unit_ids"]),
        )
        if analysis["intervals_available"]:
            item.update(
                earliest=a["earliest"],
                latest=a["latest"],
                fixed=a["fixed"],
                rank=a["rank"],
            )
        units_out.append(item)

    rels_out = []
    for r in relations:
        rr = dict(r)
        if r["rel_type"] != engine.INTERSECTS:
            f, t = engine.normalize_edge(r)
            rr["from_unit"] = f
            rr["to_unit"] = t
        rels_out.append(rr)

    # 拓扑序 -> 用单元 id 展开，供前端直接展示
    topo_units: list[list[int]] = []
    if analysis["intervals_available"]:
        topo_units = [groups_by_id[g]["unit_ids"] for g in analysis["topo_order"]]

    return {
        "consistent": analysis["consistent"],
        "intervals_available": analysis["intervals_available"],
        "conflicts": analysis["conflicts"],
        "groups": analysis["groups"],
        "units": units_out,
        "relations": rels_out,
        "edges": analysis["edges"],
        "topo_groups": analysis["topo_order"],
        "topo_units": topo_units,
        "implied_pairs": analysis["implied_pairs"],
        "conflict_unit_ids": analysis["conflict_unit_ids"],
        "conflict_group_ids": analysis["conflict_group_ids"],
        "reason_labels": REASON_LABELS,
    }


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
@app.get("/api/state")
def api_state(conn=Depends(get_db)):
    return build_state(conn)


@app.post("/api/units", status_code=201)
def api_add_unit(payload: UnitIn, conn=Depends(get_db)):
    exists = conn.execute(
        "SELECT id FROM units WHERE code = ?", (payload.code,)
    ).fetchone()
    if exists:
        raise HTTPException(409, f"编号 {payload.code} 已存在")
    cur = conn.execute(
        "INSERT INTO units (code, name, kind, note) VALUES (?,?,?,?)",
        (payload.code, payload.name, payload.kind, payload.note),
    )
    state = build_state(conn)
    state["affected"] = [{"unit_id": cur.lastrowid, "reasons": ["new_unit"]}]
    return state


@app.delete("/api/units/{unit_id}", status_code=200)
def api_delete_unit(unit_id: int, conn=Depends(get_db)):
    before = _unit_snapshot(
        engine.analyze(list_units(conn), list_relations(conn))
    )
    if conn.execute("SELECT 1 FROM units WHERE id = ?", (unit_id,)).fetchone() is None:
        raise HTTPException(404, "单元不存在")
    conn.execute("DELETE FROM units WHERE id = ?", (unit_id,))
    after = _unit_snapshot(
        engine.analyze(list_units(conn), list_relations(conn))
    )
    state = build_state(conn)
    state["affected"] = _diff_snapshots(before, after)
    return state


@app.post("/api/relations", status_code=201)
def api_add_relation(payload: RelationIn, conn=Depends(get_db)):
    if payload.source_id == payload.target_id:
        raise HTTPException(400, "关系两端不能是同一单元（自反关系无意义）")
    if conn.execute(
        "SELECT 1 FROM units WHERE id = ?", (payload.source_id,)
    ).fetchone() is None:
        raise HTTPException(404, f"单元 #{payload.source_id} 不存在")
    if conn.execute(
        "SELECT 1 FROM units WHERE id = ?", (payload.target_id,)
    ).fetchone() is None:
        raise HTTPException(404, f"单元 #{payload.target_id} 不存在")

    dup = find_relation(
        conn, payload.source_id, payload.target_id, payload.rel_type
    )
    if dup:
        raise HTTPException(
            409,
            f"等价关系已存在（#{dup['id']}：{dup['source_id']} → "
            f"{dup['target_id']} {dup['rel_type']}）",
        )

    before = _unit_snapshot(
        engine.analyze(list_units(conn), list_relations(conn))
    )
    cur = conn.execute(
        "INSERT INTO relations (source_id, target_id, rel_type, note) "
        "VALUES (?,?,?,?)",
        (payload.source_id, payload.target_id, payload.rel_type, payload.note),
    )
    after = _unit_snapshot(
        engine.analyze(list_units(conn), list_relations(conn))
    )
    state = build_state(conn)
    state["affected"] = _diff_snapshots(before, after)
    state["new_relation_id"] = cur.lastrowid
    return state


@app.delete("/api/relations/{relation_id}", status_code=200)
def api_delete_relation(relation_id: int, conn=Depends(get_db)):
    rel = conn.execute(
        "SELECT * FROM relations WHERE id = ?", (relation_id,)
    ).fetchone()
    if not rel:
        raise HTTPException(404, "关系不存在")
    before = _unit_snapshot(
        engine.analyze(list_units(conn), list_relations(conn))
    )
    conn.execute("DELETE FROM relations WHERE id = ?", (relation_id,))
    after = _unit_snapshot(
        engine.analyze(list_units(conn), list_relations(conn))
    )
    state = build_state(conn)
    state["affected"] = _diff_snapshots(before, after)
    return state


# --------------------------------------------------------------------------- #
# 演示数据 / 清空 / 导出
# --------------------------------------------------------------------------- #
DEMO_UNITS = [
    # code, name, kind
    ("L5", "第5层（生土）", "layer"),
    ("H9", "灰坑 H9", "pit"),
    ("M6", "墓葬 M6", "tomb"),
    ("F7", "房址 F7", "other"),
    ("Z8", "灶址 Z8", "ash"),
    ("L4", "第4层", "layer"),
    ("H10", "灰坑 H10（侧出）", "pit"),
    ("L3", "第3层", "layer"),
    ("L2", "第2层", "layer"),
    ("L1", "第1层（耕土）", "layer"),
]

DEMO_RELATIONS = [
    # (source_code, target_code, rel_type)
    ("L5", "H9", "intersects"),
    ("L5", "M6", "earlier"),
    ("H9", "F7", "earlier"),
    ("M6", "F7", "earlier"),
    ("F7", "Z8", "intersects"),
    ("F7", "L4", "earlier"),
    ("L4", "H10", "earlier"),
    ("L4", "L3", "earlier"),
    ("L3", "L2", "earlier"),
    ("L2", "L1", "earlier"),
]


def _load_demo(conn) -> None:
    conn.execute("DELETE FROM relations")
    conn.execute("DELETE FROM units")
    conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('units','relations')")
    ids: dict[str, int] = {}
    for code, name, kind in DEMO_UNITS:
        cur = conn.execute(
            "INSERT INTO units (code, name, kind) VALUES (?,?,?)",
            (code, name, kind),
        )
        ids[code] = cur.lastrowid
    for src, dst, rtype in DEMO_RELATIONS:
        conn.execute(
            "INSERT INTO relations (source_id, target_id, rel_type) VALUES (?,?,?)",
            (ids[src], ids[dst], rtype),
        )


@app.post("/api/reset/demo")
def api_reset_demo(conn=Depends(get_db)):
    _load_demo(conn)
    state = build_state(conn)
    state["affected"] = []
    return state


@app.post("/api/reset/clear")
def api_reset_clear(conn=Depends(get_db)):
    conn.execute("DELETE FROM relations")
    conn.execute("DELETE FROM units")
    conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('units','relations')")
    state = build_state(conn)
    state["affected"] = []
    return state


@app.get("/api/export")
def api_export(conn=Depends(get_db)):
    from datetime import datetime

    state = build_state(conn)
    payload = {
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "tool": "archaeo-stratigraphy-console",
        "version": "1.0.0",
        "units": state["units"],
        "relations": state["relations"],
        "analysis": {
            "consistent": state["consistent"],
            "groups": state["groups"],
            "edges": state["edges"],
            "topo_groups": state["topo_groups"],
            "topo_units": state["topo_units"],
            "implied_pairs": state["implied_pairs"],
            "conflicts": state["conflicts"],
        },
    }
    return JSONResponse(
        content=payload,
        headers={
            "Content-Disposition": "attachment; filename=stratigraphy_export.json"
        },
    )


# --------------------------------------------------------------------------- #
# 前端静态资源
# --------------------------------------------------------------------------- #
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index():
    return RedirectResponse("/static/index.html")


init_db()
