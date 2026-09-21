"""地层关系推演核心算法（纯函数，不依赖数据库）。

关系语义
--------
- earlier:  A 早于 B  ->  A -> B（A 位于 B 下方）
- later:    A 晚于 B  ->  B -> A
- intersects: A 与 B 相交（同层位/共存），视为对称、可传递的等价关系

先把所有 intersects 连通分量收缩成"共存组"，再在组间有向图上做：
1. 矛盾环检测（含跨环相交矛盾，例如 A 早于 B、B 早于 C、A 又与 C 相交）；
2. 拓扑排序与可达闭包；
3. 计算每个单元最早 / 最晚可能层位区间：
   earliest(g) = 组 g 的祖先组数 + 1
   latest(g)   = 组总数 - 组 g 的后代组数
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

EARLIER = "earlier"
LATER = "later"
INTERSECTS = "intersects"
REL_TYPES = (EARLIER, LATER, INTERSECTS)

REL_LABELS = {
    EARLIER: "早于",
    LATER: "晚于",
    INTERSECTS: "相交",
}


# --------------------------------------------------------------------------- #
# 并查集：相交关系 -> 共存组
# --------------------------------------------------------------------------- #
class DSU:
    def __init__(self, items):
        self.parent = {x: x for x in items}

    def find(self, x):
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != x:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def normalize_edge(r: dict) -> tuple[int, int]:
    """把任意关系归一化为 (from -> to)，from 为较早单元。"""
    a, b = r["source_id"], r["target_id"]
    return (a, b) if r["rel_type"] == EARLIER else (b, a)


# --------------------------------------------------------------------------- #
# 主分析函数
# --------------------------------------------------------------------------- #
def analyze(units: list[dict], relations: list[dict]) -> dict[str, Any]:
    unit_ids = [u["id"] for u in units]
    id_set = set(unit_ids)

    # 仅保留两端仍存在的关系（删除单元后可能出现悬挂关系，正常会被级联删除）
    rels = [
        r
        for r in relations
        if r["source_id"] in id_set and r["target_id"] in id_set
    ]

    intersects, directed_raw, self_loop = [], [], []
    for r in rels:
        a, b = r["source_id"], r["target_id"]
        if a == b:
            self_loop.append(r)
        elif r["rel_type"] == INTERSECTS:
            intersects.append(r)
        else:
            directed_raw.append(r)

    # 1) 收缩共存组 ---------------------------------------------------------
    dsu = DSU(unit_ids)
    for r in intersects:
        dsu.union(r["source_id"], r["target_id"])

    members: dict[int, list[int]] = defaultdict(list)
    for uid in unit_ids:
        members[dsu.find(uid)].append(uid)

    # 组号采用稳定编号：按组内最小单元 id 排序
    roots = sorted(members, key=lambda g: min(members[g]))
    group_of: dict[int, int] = {}
    groups: list[dict] = []
    for idx, root in enumerate(roots, start=1):
        g = {
            "id": idx,
            "unit_ids": sorted(members[root]),
        }
        groups.append(g)
        for uid in g["unit_ids"]:
            group_of[uid] = idx

    # 2) 组间有向边 + 组内自相矛盾（同一共存组内部出现时序关系） ----------------
    edge_rel: dict[tuple[int, int], list[int]] = defaultdict(list)
    intra_conflicts: list[dict] = []
    for r in directed_raw:
        a, b = normalize_edge(r)
        ga, gb = group_of[a], group_of[b]
        if ga == gb:
            intra_conflicts.append(
                {
                    "kind": "intra_intersects",
                    "relation_ids": [r["id"]],
                    "group_id": ga,
                    "unit_ids": sorted(
                        set(groups[ga - 1]["unit_ids"]) | {a, b}
                    ),
                    "message": (
                        f"共存组 G{ga} 内部出现时序关系 #{r['id']}（"
                        f"{r['source_id']} {REL_LABELS[r['rel_type']]} "
                        f"{r['target_id']}），与“相交”矛盾"
                    ),
                }
            )
        else:
            edge_rel[(ga, gb)].append(r["id"])

    # 自反环（A 早于/晚于 A，或 A 与自己相交）
    for r in self_loop:
        intra_conflicts.append(
            {
                "kind": "self_loop",
                "relation_ids": [r["id"]],
                "group_id": group_of.get(r["source_id"]),
                "unit_ids": [r["source_id"]],
                "message": (
                    f"关系 #{r['id']} 指向单元自身"
                    f"（{r['source_id']} {REL_LABELS.get(r['rel_type'], r['rel_type'])} 自身）"
                ),
            }
        )

    edges = [(ga, gb) for ga, gb in edge_rel]
    adj: dict[int, set[int]] = defaultdict(set)
    radj: dict[int, set[int]] = defaultdict(set)
    for ga, gb in edges:
        adj[ga].add(gb)
        radj[gb].add(ga)

    n_groups = len(groups)
    all_groups = {g["id"] for g in groups}

    # 3) 环检测（DFS，收集每条回边上的一个环）--------------------------------
    cycles = _find_cycles(all_groups, adj, edge_rel, groups, group_of)

    conflicts = cycles + _merge_intra_conflicts(intra_conflicts)
    consistent = not conflicts
    conflict_group_ids: set[int] = set()
    conflict_unit_ids: set[int] = set()
    for c in conflicts:
        conflict_group_ids.update(c.get("group_ids", []))
        conflict_unit_ids.update(c.get("unit_ids", []))

    # 4) 无矛盾时计算拓扑序、可达闭包、层位区间、布局层级 ----------------------
    intervals_available = consistent
    topo: list[int] = []
    rank: dict[int, int] = {}
    ancestors: dict[int, set[int]] = {}
    descendants: dict[int, set[int]] = {}
    implied_pairs = 0

    if consistent:
        topo = _topo_sort(all_groups, adj)

        # 可达闭包（按拓扑序传播）
        anc: dict[int, set[int]] = {g: set() for g in all_groups}
        desc: dict[int, set[int]] = {g: set() for g in all_groups}
        for g in topo:
            for p in radj.get(g, ()):
                anc[g] |= anc[p] | {p}
        for g in reversed(topo):
            for c in adj.get(g, ()):
                desc[g] |= desc[c] | {c}
        ancestors, descendants = anc, desc

        explicit_pairs = len(edges)
        reachable_pairs = sum(len(v) for v in desc.values())
        implied_pairs = max(0, reachable_pairs - explicit_pairs)

        # 布局层级（自下而上）：最长前驱链长度
        for g in topo:
            rank[g] = (
                1 + max((rank[p] for p in radj.get(g, ())), default=0)
            )

    unit_out: dict[int, dict] = {}
    for u in units:
        uid, gid = u["id"], group_of[u["id"]]
        item: dict[str, Any] = {
            "unit_id": uid,
            "group_id": gid,
            "conflicted": uid in conflict_unit_ids,
        }
        if intervals_available:
            earliest = len(ancestors[gid]) + 1
            latest = n_groups - len(descendants[gid])
            item.update(
                earliest=earliest,
                latest=latest,
                fixed=earliest == latest,
                rank=rank[gid],
            )
        unit_out[uid] = item

    groups_out = []
    for g in groups:
        entry: dict[str, Any] = {
            "id": g["id"],
            "unit_ids": g["unit_ids"],
            "size": len(g["unit_ids"]),
            "conflicted": g["id"] in conflict_group_ids,
        }
        if intervals_available:
            entry.update(
                earliest=len(ancestors[g["id"]]) + 1,
                latest=n_groups - len(descendants[g["id"]]),
                rank=rank[g["id"]],
            )
        groups_out.append(entry)

    # 归一化的有向边（供前端绘制关系图）
    edges_out = [
        {
            "from_group": ga,
            "to_group": gb,
            "relation_ids": sorted(edge_rel[(ga, gb)]),
        }
        for ga, gb in sorted(edges)
    ]

    return {
        "consistent": consistent,
        "intervals_available": intervals_available,
        "conflicts": conflicts,
        "groups": groups_out,
        "group_of": group_of,
        "units": unit_out,
        "edges": edges_out,
        "intersect_relations": [r["id"] for r in intersects],
        "topo_order": topo if intervals_available else [],
        "implied_pairs": implied_pairs,
        "conflict_unit_ids": sorted(conflict_unit_ids),
        "conflict_group_ids": sorted(conflict_group_ids),
    }


# --------------------------------------------------------------------------- #
# 环检测
# --------------------------------------------------------------------------- #
def _find_cycles(all_groups, adj, edge_rel, groups, group_of):
    """DFS 环检测；每遇到一条回边，回溯出环上的组与单元。"""
    color: dict[int, int] = {g: 0 for g in all_groups}  # 0白 1灰 2黑
    stack: list[int] = []
    on_stack: dict[int, int] = {}
    cycles: list[dict] = []
    seen_cycles: set[tuple[int, ...]] = set()

    def dfs(u):
        color[u] = 1
        on_stack[u] = len(stack)
        stack.append(u)
        for v in sorted(adj.get(u, ())):
            if color[v] == 0:
                dfs(v)
            elif color[v] == 1:
                idx = on_stack[v]
                cyc_groups = stack[idx:] + [v]
                key = tuple(sorted(cyc_groups[:-1]))
                if key in seen_cycles:
                    continue
                seen_cycles.add(key)
                relation_ids = []
                for a, b in zip(cyc_groups, cyc_groups[1:]):
                    relation_ids.extend(edge_rel.get((a, b), []))
                unit_ids = sorted(
                    {uid for g in cyc_groups for uid in groups[g - 1]["unit_ids"]}
                )
                chains = [
                    " → ".join(
                        "G%d(%s)"
                        % (g, "/".join("U%d" % i for i in groups[g - 1]["unit_ids"]))
                        for g in cyc_groups
                    )
                ]
                cycles.append(
                    {
                        "kind": "cycle",
                        "group_ids": sorted(set(cyc_groups)),
                        "unit_ids": unit_ids,
                        "relation_ids": sorted(set(relation_ids)),
                        "cycle_groups": cyc_groups,
                        "message": "检测到矛盾时序环：" + chains[0],
                    }
                )
        stack.pop()
        del on_stack[u]
        color[u] = 2

    import sys

    sys.setrecursionlimit(max(10000, len(all_groups) * 4 + 1000))
    for g in sorted(all_groups):
        if color[g] == 0:
            dfs(g)
    return cycles


def _merge_intra_conflicts(conflicts):
    """同一共存组内的多条时序矛盾合并展示。"""
    by_group: dict[int, dict] = {}
    standalone = []
    for c in conflicts:
        if c["kind"] != "intra_intersects":
            standalone.append(c)
            continue
        gid = c["group_id"]
        if gid not in by_group:
            by_group[gid] = {
                "kind": "intra_intersects",
                "group_ids": [gid],
                "group_id": gid,
                "relation_ids": [],
                "unit_ids": set(),
                "message": "",
            }
        m = by_group[gid]
        m["relation_ids"].extend(c["relation_ids"])
        m["unit_ids"].update(c["unit_ids"])
    out = list(standalone)
    for gid in sorted(by_group):
        m = by_group[gid]
        m["relation_ids"] = sorted(set(m["relation_ids"]))
        m["unit_ids"] = sorted(m["unit_ids"])
        m["message"] = (
            f"共存组 G{gid}（{'/'.join('U%d' % i for i in m['unit_ids'])}）"
            f"内部存在 {len(m['relation_ids'])} 条时序关系，"
            "与“相交=同时期”矛盾"
        )
        out.append(m)
    return out


# --------------------------------------------------------------------------- #
# 拓扑排序（组编号做确定性平局规则）
# --------------------------------------------------------------------------- #
def _topo_sort(all_groups, adj):
    indeg = {g: 0 for g in all_groups}
    for u in all_groups:
        for v in adj.get(u, ()):
            indeg[v] += 1
    ready = sorted(g for g, d in indeg.items() if d == 0)
    order = []
    while ready:
        u = ready.pop(0)
        order.append(u)
        for v in sorted(adj.get(u, ())):
            indeg[v] -= 1
            if indeg[v] == 0:
                ready.append(v)
                ready.sort()
    return order
