"""考古地层关系推演台 —— FastAPI 入口。"""
from __future__ import annotations

import datetime as dt
import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db, logic, seed
from .schemas import RelationCreate, UnitCreate, UnitUpdate


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="考古地层关系推演台", version="1.0.0", lifespan=lifespan)

# 一次推演只涉及少量数据，用一把锁串行化写入，避免 affected 标记串号
_write_lock = threading.Lock()

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


# ------------------------------------------------------------------
# 状态组装
# ------------------------------------------------------------------

def build_state(conn, affected: list[str] | None = None) -> dict:
    state = db.snapshot(conn)
    return {
        "units": state["units"],
        "relations": state["relations"],
        "analysis": logic.analyze(state),
        "affected": affected or [],
    }


def require_unit(conn, unit_id: str) -> None:
    row = conn.execute("SELECT 1 FROM units WHERE id = ?", (unit_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"地层单元 {unit_id} 不存在")


def is_duplicate(conn, rel: RelationCreate) -> bool:
    """同一对单元之间的等价关系视为重复。

    比较前统一规范化：相交为无向关系；早晚关系规范化为
    （较早单元, 较晚单元）方向。同序为重复，反序留给推演层判矛盾。
    """
    if rel.kind == logic.INTERSECTS:
        src_kind = logic.INTERSECTS
    else:
        src_kind = logic.EARLIER
    # 规范化待插入关系
    if rel.kind == logic.LATER:
        new_a, new_b = rel.target_id, rel.source_id
    else:
        new_a, new_b = rel.source_id, rel.target_id

    rows = conn.execute(
        """SELECT kind, source_id, target_id FROM relations
           WHERE (source_id = ? AND target_id = ?)
              OR (source_id = ? AND target_id = ?)""",
        (rel.source_id, rel.target_id, rel.target_id, rel.source_id),
    ).fetchall()
    for row in rows:
        kind = row["kind"]
        if kind == logic.INTERSECTS:
            if src_kind == logic.INTERSECTS:
                return True
            continue
        if src_kind == logic.EARLIER:
            ex_a, ex_b = row["source_id"], row["target_id"]
            if kind == logic.LATER:
                ex_a, ex_b = ex_b, ex_a
            if (ex_a, ex_b) == (new_a, new_b):
                return True
    return False


# ------------------------------------------------------------------
# API
# ------------------------------------------------------------------

@app.get("/api/state")
def get_state() -> dict:
    with db.get_conn() as conn:
        return build_state(conn)


@app.post("/api/units", status_code=201)
def create_unit(payload: UnitCreate) -> dict:
    with _write_lock, db.get_conn() as conn:
        exists = conn.execute("SELECT 1 FROM units WHERE id = ?", (payload.id,)).fetchone()
        if exists:
            raise HTTPException(status_code=409, detail=f"编号 {payload.id} 已存在")
        conn.execute(
            "INSERT INTO units (id, name, note) VALUES (?, ?, ?)",
            (payload.id, payload.name, payload.note),
        )
        # 新单元对推演结果无影响，但仍标记其自身为“受影响（新增）”
        return build_state(conn, [payload.id])


@app.patch("/api/units/{unit_id}")
def update_unit(unit_id: str, payload: UnitUpdate) -> dict:
    with _write_lock, db.get_conn() as conn:
        require_unit(conn, unit_id)
        conn.execute(
            "UPDATE units SET name = ?, note = ? WHERE id = ?",
            (payload.name, payload.note, unit_id),
        )
        return build_state(conn)


@app.delete("/api/units/{unit_id}")
def delete_unit(unit_id: str) -> dict:
    with _write_lock, db.get_conn() as conn:
        require_unit(conn, unit_id)
        before = logic.unit_signature(db.snapshot(conn))
        # 相关关系通过 ON DELETE CASCADE 一并删除
        conn.execute("DELETE FROM units WHERE id = ?", (unit_id,))
        state = db.snapshot(conn)
        affected = set(logic.affected_units(before, state))
        result = logic.analyze(state)
        affected |= set(result["conflict_unit_ids"])
        return {
            "units": state["units"],
            "relations": state["relations"],
            "analysis": result,
            "affected": sorted(affected),
            "deleted_unit": unit_id,
        }


@app.post("/api/relations", status_code=201)
def create_relation(payload: RelationCreate) -> dict:
    if payload.source_id == payload.target_id:
        raise HTTPException(status_code=400, detail="一条关系的两端必须是不同的地层单元")
    with _write_lock, db.get_conn() as conn:
        require_unit(conn, payload.source_id)
        require_unit(conn, payload.target_id)
        if is_duplicate(conn, payload):
            raise HTTPException(status_code=409, detail="这两个单元之间已存在等价关系，请勿重复录入")

        before = logic.unit_signature(db.snapshot(conn))
        cur = conn.execute(
            "INSERT INTO relations (kind, source_id, target_id, note) VALUES (?, ?, ?, ?)",
            (payload.kind, payload.source_id, payload.target_id, payload.note),
        )
        new_id = cur.lastrowid

        state = db.snapshot(conn)
        affected = set(logic.affected_units(before, state))
        # 新增关系直接触及的两个单元一定标为受影响
        affected |= {payload.source_id, payload.target_id}
        response = {
            "units": state["units"],
            "relations": state["relations"],
            "analysis": logic.analyze(state),
            "affected": sorted(affected),
            "new_relation_id": new_id,
        }
        return response


@app.delete("/api/relations/{rel_id}")
def delete_relation(rel_id: int) -> dict:
    with _write_lock, db.get_conn() as conn:
        row = conn.execute("SELECT * FROM relations WHERE id = ?", (rel_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"关系 #{rel_id} 不存在")
        before = logic.unit_signature(db.snapshot(conn))
        conn.execute("DELETE FROM relations WHERE id = ?", (rel_id,))
        state = db.snapshot(conn)
        affected = set(logic.affected_units(before, state))
        affected |= {row["source_id"], row["target_id"]}
        return {
            "units": state["units"],
            "relations": state["relations"],
            "analysis": logic.analyze(state),
            "affected": sorted(affected),
        }


@app.post("/api/sample", status_code=201)
def load_sample() -> dict:
    """清空并载入示例数据。"""
    with _write_lock, db.get_conn() as conn:
        conn.execute("DELETE FROM relations")
        conn.execute("DELETE FROM units")
        for uid, name, note in seed.SAMPLE_UNITS:
            conn.execute(
                "INSERT INTO units (id, name, note) VALUES (?, ?, ?)", (uid, name, note)
            )
        for kind, src, tgt in seed.SAMPLE_RELATIONS:
            conn.execute(
                "INSERT INTO relations (kind, source_id, target_id, note) VALUES (?, ?, ?, '')",
                (kind, src, tgt),
            )
        return build_state(conn)


@app.post("/api/reset")
def reset_all() -> dict:
    with _write_lock, db.get_conn() as conn:
        conn.execute("DELETE FROM relations")
        conn.execute("DELETE FROM units")
        return build_state(conn)


@app.get("/api/export")
def export_json() -> JSONResponse:
    with db.get_conn() as conn:
        state = db.snapshot(conn)
    payload = {
        "exported_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "units": state["units"],
        "relations": state["relations"],
        "analysis": logic.analyze(state),
    }
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": "attachment; filename=strata_export.json"},
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# 静态前端（放在 API 之后挂载）
@app.get("/")
def index() -> FileResponse:
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
