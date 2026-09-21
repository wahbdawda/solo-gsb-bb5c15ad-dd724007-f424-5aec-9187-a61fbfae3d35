"""地层关系推演核心：

- 关系归一化（later_than 视为反向 earlier_than；intersects 为无向共存关系）
- “相交”单元用并查集合为共存组
- 矛盾检测：
  1. 同共存组内部出现时序关系（相交且有早晚，逻辑矛盾）
  2. 共存组之间的时序 DAG 出现有向环（早于关系闭环）
- 无矛盾时计算每个单元在全部可行拓扑序中的层位位置区间（M = 共存组总数）：
  earliest = 必须先于该组的组数（前驱传递闭包大小）+ 1
  latest   = M − 必须晚于该组的组数（后继传递闭包大小）
  （决定位置上下界的是可达顶点的“个数”，而非最长链长度）
"""
from __future__ import annotations

import sys
from typing import Optional

sys.setrecursionlimit(20000)

EARLIER = "earlier_than"
LATER = "later_than"
INTERSECTS = "intersects"
TIME_KINDS = (EARLIER, LATER)


def normalize(relations: list[dict]) -> list[dict]:
    """later_than(a,b) 规范化为 earlier_than(b,a)，其余保持。"""
    out: list[dict] = []
    for r in relations:
        if r["kind"] == LATER:
            out.append(
                {
                    "id": r["id"],
                    "kind": EARLIER,
                    "source_id": r["target_id"],
                    "target_id": r["source_id"],
                    "note": r.get("note", ""),
                }
            )
        else:
            out.append(dict(r))
    return out


class DSU:
    def __init__(self, members: list[str]):
        self.parent = {m: m for m in members}
        self.members = {m: {m} for m in members}

    def find(self, x: str) -> str:
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != x:
            nxt = self.parent[x]
            self.parent[x] = root
            x = nxt
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        # 用字典序最小的单元作为组代表，保证结果确定
        if rb < ra:
            ra, rb = rb, ra
        self.parent[rb] = ra
        # 合并后成员表必须挂在最终的根（ra）下
        self.members[ra] = self.members[ra] | self.members[rb]
        del self.members[rb]


def _find_cycle(adj: dict[str, set[str]], edge_rel: dict[tuple[str, str], int],
                members: list[str]) -> list[str]:
    """在给定强连通分量内用 DFS 找一条具体有向环，返回组代表序列。"""
    allowed = set(members)
    color: dict[str, int] = {m: 0 for m in members}  # 0 未访问, 1 在路径上, 2 完成
    stack: list[str] = []

    def dfs(u: str) -> Optional[list[str]]:
        color[u] = 1
        stack.append(u)
        for v in sorted(adj[u]):
            if v not in allowed:
                continue
            if color[v] == 0:
                found = dfs(v)
                if found is not None:
                    return found
            elif color[v] == 1:  # 回到当前路径上的祖先 => 找到环
                idx = stack.index(v)
                return stack[idx:] + [v]
        stack.pop()
        color[u] = 2
        return None

    for m in sorted(members):
        if color[m] == 0:
            found = dfs(m)
            if found is not None:
                return found
    return [members[0], members[0]]


def _tarjan_scc(nodes: list[str], adj: dict[str, set[str]]) -> list[list[str]]:
    index = 0
    indices: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    sccs: list[list[str]] = []

    def strongconnect(v: str) -> None:
        nonlocal index
        indices[v] = low[v] = index
        index += 1
        stack.append(v)
        on_stack.add(v)
        for w in sorted(adj[v]):
            if w not in indices:
                strongconnect(w)
                low[v] = min(low[v], low[w])
            elif w in on_stack:
                low[v] = min(low[v], indices[w])
        if low[v] == indices[v]:
            comp: list[str] = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                comp.append(w)
                if w == v:
                    break
            sccs.append(sorted(comp))

    for n in sorted(nodes):
        if n not in indices:
            strongconnect(n)
    return sccs


def analyze(state: dict) -> dict:
    """对 {units, relations} 做完整推演，返回前端/导出所需的全部结果。"""
    units = state["units"]
    unit_ids = [u["id"] for u in units]
    relations = normalize(state["relations"])

    dsu = DSU(unit_ids)
    temporal: list[dict] = []
    for r in relations:
        if r["kind"] == INTERSECTS:
            dsu.union(r["source_id"], r["target_id"])
        else:
            temporal.append(r)

    # 组的成员表（含孤立单元）
    comp_members: dict[str, list[str]] = {
        rep: sorted(ms) for rep, ms in dsu.members.items()
    }
    unit_comp = {u: rep for rep, ms in comp_members.items() for u in ms}

    conflicts: list[dict] = []
    conflict_unit_ids: set[str] = set()
    conflict_rel_ids: set[int] = set()

    # 组间时序图
    adj: dict[str, set[str]] = {rep: set() for rep in comp_members}
    radj: dict[str, set[str]] = {rep: set() for rep in comp_members}
    edge_rel: dict[tuple[str, str], int] = {}
    intra_temporal: dict[str, list[dict]] = {}

    for r in temporal:
        a, b = r["source_id"], r["target_id"]
        if a not in unit_comp or b not in unit_comp:
            continue  # 单元已删除等脏数据
        ca, cb = unit_comp[a], unit_comp[b]
        if ca == cb:
            # 矛盾类型 1：相交（共存）单元之间声明了早晚关系 —— 先收集，稍后汇总
            intra_temporal.setdefault(ca, []).append(r)
            continue
        # 反向边也是矛盾（A早于B 且 B早于A），先入图由环检测统一捕获
        adj[ca].add(cb)
        radj[cb].add(ca)
        edge_rel[(ca, cb)] = r["id"]

    # 矛盾类型 1：相交（共存）组内部又声明了早晚关系
    for ca, rels_in in sorted(intra_temporal.items()):
        members = comp_members[ca]
        internal_intersect_ids = intersect_rel_ids_on_pair(relations, members)
        temporal_ids = {r["id"] for r in rels_in}
        # 仅当该组确实由“相交”关系聚合时才构成语义矛盾
        if internal_intersect_ids:
            pairs = "、".join(f"{r['source_id']}→{r['target_id']}" for r in rels_in)
            conflicts.append({
                "type": "intersect_with_order",
                "message": f"共存组（{ '、'.join(members) }）内部既声明“相交”同期，"
                           f"又存在早晚关系（{pairs}），自相矛盾。",
                "cycle": members,
                "relation_ids": sorted(internal_intersect_ids | temporal_ids),
            })
            conflict_unit_ids.update(members)
            conflict_rel_ids |= internal_intersect_ids | temporal_ids

    # 矛盾类型 2：组时序图中的有向环（含两点互指）
    if not conflicts:
        for comp in _tarjan_scc(list(comp_members), adj):
            if len(comp) > 1 or (len(comp) == 1 and comp[0] in adj[comp[0]]):
                cyc_reps = _find_cycle(adj, edge_rel, comp)
                cyc_units: list[str] = []
                rel_ids: list[int] = []
                for i, rep in enumerate(cyc_reps[:-1]):
                    cyc_units.extend(comp_members[rep])
                    nxt = cyc_reps[i + 1]
                    rid = edge_rel.get((rep, nxt))
                    if rid is not None:
                        rel_ids.append(rid)
                conflicts.append({
                    "type": "cyclic_order",
                    "message": "早晚关系形成闭环（"
                               + " → ".join(_label_of(x, comp_members) for x in cyc_reps)
                               + "），地层不可能互为先后。",
                    "cycle": sorted(set(cyc_units)),
                    "relation_ids": sorted(set(rel_ids)),
                })
                for rep in cyc_reps:
                    conflict_unit_ids.update(comp_members[rep])
                conflict_rel_ids.update(rel_ids)

    has_conflict = bool(conflicts)

    intervals: dict[str, Optional[dict]] = {uid: None for uid in unit_ids}
    comp_levels: dict[str, int] = {}
    total_levels = 0

    if not has_conflict:
        # 拓扑序长度 = 堆积单位（共存组）总数
        total_levels = len(comp_members)
        rep_list = sorted(comp_members)
        idx = {rep: i for i, rep in enumerate(rep_list)}
        m = len(rep_list)

        # Warshall 传递闭包（布尔矩阵，标准三重循环）
        reach = [[False] * m for _ in range(m)]
        for rep in rep_list:
            for nxt in adj[rep]:
                reach[idx[rep]][idx[nxt]] = True
        for mid in range(m):
            col = [reach[i][mid] for i in range(m)]
            row = reach[mid]
            for i in range(m):
                if col[i]:
                    for j in range(m):
                        if row[j]:
                            reach[i][j] = True

        earliest: dict[str, int] = {}
        latest: dict[str, int] = {}
        for rep in rep_list:
            i = idx[rep]
            preds = sum(1 for x in range(m) if reach[x][i])
            succs = sum(1 for x in range(m) if reach[i][x])
            earliest[rep] = preds + 1
            latest[rep] = total_levels - succs

        for rep, members in comp_members.items():
            comp_levels[rep] = earliest[rep]
            for uid in members:
                intervals[uid] = {
                    "earliest": earliest[rep],
                    "latest": latest[rep],
                }

    return {
        "has_conflict": has_conflict,
        "conflicts": conflicts,
        "conflict_unit_ids": sorted(conflict_unit_ids),
        "conflict_relation_ids": sorted(conflict_rel_ids),
        "components": [
            {
                "id": rep,
                "members": members,
                "level": comp_levels.get(rep),
            }
            for rep, members in sorted(comp_members.items())
        ],
        "total_levels": total_levels,
        "intervals": intervals,
    }


def _label_of(rep: str, comp_members: dict[str, list[str]]) -> str:
    members = comp_members[rep]
    if len(members) == 1:
        return members[0]
    return "{" + "/".join(members) + "}"


def intersect_rel_ids_on_pair(relations: list[dict], members: list[str]) -> set[int]:
    mset = set(members)
    return {
        r["id"]
        for r in relations
        if r["kind"] == INTERSECTS
        and r["source_id"] in mset
        and r["target_id"] in mset
    }


# ------------------------------------------------------------------
# 受影响节点追踪
# ------------------------------------------------------------------

def unit_signature(state: dict) -> dict[str, tuple]:
    """每个单元的推演结果指纹（共存组成员 + 层位区间 + 是否在冲突中）。"""
    result = analyze(state)
    comp_of = {}
    for c in result["components"]:
        for m in c["members"]:
            comp_of[m] = tuple(c["members"])
    return {
        u["id"]: (
            comp_of.get(u["id"], (u["id"],)),
            None if result["intervals"][u["id"]] is None
            else (result["intervals"][u["id"]]["earliest"],
                  result["intervals"][u["id"]]["latest"]),
            u["id"] in set(result["conflict_unit_ids"]),
        )
        for u in state["units"]
    }


def affected_units(before: dict[str, tuple], after_state: dict) -> list[str]:
    after = unit_signature(after_state)
    changed = [
        uid
        for uid, sig in after.items()
        if uid not in before or before.get(uid) != sig
    ]
    # 被删除的单元不算“受影响节点”（已不存在）
    return sorted(changed)
