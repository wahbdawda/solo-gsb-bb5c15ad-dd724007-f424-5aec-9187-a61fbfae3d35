/* 考古地层关系推演台 — 前端逻辑（无框架，原生 JS） */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];

const REL_LABEL = { earlier: "早于", later: "晚于", intersects: "相交" };
const REL_CLASS = { earlier: "rel-earlier", later: "rel-later", intersects: "rel-intersects" };
const KIND_LABEL = {
  layer: "地层", pit: "灰坑", wall: "墙基", ditch: "沟壕",
  tomb: "墓葬", ash: "灶/灰", other: "遗迹",
};
const CONFLICT_KIND_LABEL = {
  cycle: "矛盾时序环",
  intra_intersects: "相交组内时序矛盾",
  self_loop: "自反关系",
};

let state = null;
let affectedMap = new Map(); // unitId -> [reasons]
const nodeSize = { w: 96, h: 42 };

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );

// --------------------------------------------------------------------------- //
// 数据加载
// --------------------------------------------------------------------------- //
async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try {
      msg = (await res.json()).detail || msg;
    } catch (_) {}
    throw new Error(msg);
  }
  return res.json();
}

async function refresh() {
  state = await api("/api/state");
  affectedMap = new Map();
  renderAll();
}

function applyState(next) {
  state = next;
  affectedMap = new Map();
  (next.affected || []).forEach((a) => affectedMap.set(a.unit_id, a.reasons));
  renderAll();
}

// --------------------------------------------------------------------------- //
// 总渲染
// --------------------------------------------------------------------------- //
function renderAll() {
  renderBadge();
  renderSelects();
  renderUnitList();
  renderRelList();
  renderGraph();
  renderAnalysis();
  renderConflicts();
  renderAffectedBanner();
}

function unitById(id) {
  return state.units.find((u) => u.id === id);
}
function unitCode(id) {
  const u = unitById(id);
  return u ? u.code : `#${id}`;
}

function renderBadge() {
  const b = $("#statusBadge");
  if (!state) return;
  if (state.units.length === 0) {
    b.textContent = "未录入数据";
    b.className = "badge idle";
  } else if (state.consistent) {
    b.textContent = `✓ 关系一致 · ${state.groups.length} 个共存组`;
    b.className = "badge ok";
  } else {
    b.textContent = `✗ ${state.conflicts.length} 处矛盾`;
    b.className = "badge err";
  }
}

// ---------------- 下拉框 ---------------- //
function renderSelects() {
  const opts = state.units
    .map((u) => `<option value="${u.id}">#${u.id} ${esc(u.code)}</option>`)
    .join("");
  ["source_id", "target_id"].forEach((name) => {
    const sel = $(`#relForm [name="${name}"]`);
    const prev = sel.value;
    sel.innerHTML =
      `<option value="">请选择…</option>` + opts;
    if (state.units.some((u) => u.id === Number(prev))) sel.value = prev;
  });
}

// ---------------- 单元列表 ---------------- //
function renderUnitList() {
  $("#unitCount").textContent = state.units.length;
  const ul = $("#unitList");
  if (!state.units.length) {
    ul.innerHTML = `<li class="meta">暂无单元</li>`;
    return;
  }
  ul.innerHTML = state.units
    .map((u) => {
      const aff = affectedMap.has(u.id);
      let tag = "";
      if (u.conflicted) tag = `<span class="tag tag-conflict">矛盾环</span>`;
      else if (state.intervals_available && u.fixed)
        tag = `<span class="tag tag-fixed">层位固定 ${u.earliest}</span>`;
      else if (state.intervals_available)
        tag = `<span class="tag">${u.earliest}–${u.latest}</span>`;
      return `
      <li class="${aff ? "affected" : ""}" data-uid="${u.id}">
        <span class="code">${esc(u.code)}</span>
        <span class="meta" title="${esc(u.name)} ${
        u.note ? "｜" + esc(u.note) : ""
      }">${esc(u.name || KIND_LABEL[u.kind] || "")}</span>
        ${tag}
        <span class="op">
          <button class="btn-link" data-act="src" title="设为关系起点（较早方）">源</button>
          <button class="btn-link" data-act="dst" title="设为关系终点">目</button>
          <button class="btn-link danger" data-act="del">删</button>
        </span>
      </li>`;
    })
    .join("");
}

// ---------------- 关系列表 ---------------- //
function renderRelList() {
  $("#relCount").textContent = state.relations.length;
  const ul = $("#relList");
  if (!state.relations.length) {
    ul.innerHTML = `<li class="meta">暂无关系</li>`;
    return;
  }
  const conflictRels = new Set();
  state.conflicts.forEach((c) => c.relation_ids.forEach((id) => conflictRels.add(id)));
  ul.innerHTML = state.relations
    .map((r) => {
      const aff = affectedMap.has(r.source_id) || affectedMap.has(r.target_id);
      return `
      <li class="${aff ? "affected" : ""}">
        <span class="rel-text">
          <b>${esc(unitCode(r.source_id))}</b>
          <span class="rel-type ${REL_CLASS[r.rel_type]}">${REL_LABEL[r.rel_type]}</span>
          <b>${esc(unitCode(r.target_id))}</b>
          ${
            conflictRels.has(r.id)
              ? `<span class="tag tag-conflict">涉冲突</span>`
              : ""
          }
        </span>
        <span class="op">
          <button class="btn-link danger" data-act="delrel" data-rid="${r.id}">删</button>
        </span>
      </li>`;
    })
    .join("");
}

// --------------------------------------------------------------------------- //
// 关系图（SVG）
// --------------------------------------------------------------------------- //
const SVGNS = "http://www.w3.org/2000/svg";
function svgEl(tag, attrs = {}, text) {
  const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  if (text != null) el.textContent = text;
  return el;
}

function renderGraph() {
  const svg = $("#graph");
  svg.innerHTML = "";
  $("#graphEmpty").classList.toggle("hidden", state.units.length > 0);

  if (!state.units.length) {
    svg.setAttribute("width", 0).setAttribute("height", 0);
    return;
  }

  // 箭头定义
  const defs = svgEl("defs");
  [["arrow", "#3d6e8f"], ["arrowRed", "#b4433a"]].forEach(([id, color]) => {
    const m = svgEl("marker", {
      id, viewBox: "0 0 10 10", refX: 9, refY: 5,
      markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse",
    });
    m.appendChild(
      svgEl("path", { d: "M0,0 L10,5 L0,10 z", fill: color })
    );
    defs.appendChild(m);
  });
  svg.appendChild(defs);

  if (state.intervals_available) drawDag(svg);
  else drawFallback(svg);
}

function drawNode(svg, x, y, uid) {
  const u = unitById(uid);
  const cls = ["node"];
  if (u.conflicted) cls.push("conflicted");
  if (affectedMap.has(uid)) cls.push("affected", "pulse");
  const g = svgEl("g", { class: cls.join(" "), transform: `translate(${x},${y})` });
  g.appendChild(svgEl("rect", { width: nodeSize.w, height: nodeSize.h }));
  g.appendChild(
    svgEl("text", { x: nodeSize.w / 2, y: 17, "text-anchor": "middle", class: "node-code" }, u.code)
  );
  if (u.name) {
    const name = u.name.length > 7 ? u.name.slice(0, 7) + "…" : u.name;
    g.appendChild(
      svgEl("text", { x: nodeSize.w / 2, y: 33, "text-anchor": "middle", class: "node-name" }, name)
    );
  }
  const reasons = affectedMap.get(uid);
  if (reasons) {
    g.appendChild(svgEl("title", {}, reasons.map((r) => state.reason_labels[r] || r).join("；")));
  }
  svg.appendChild(g);
  return { cx: x + nodeSize.w / 2, top: y, bottom: y + nodeSize.h };
}

/* 一致状态：按共存组 + 最长链层级分层，较早者画在下方 */
function drawDag(svg) {
  const pad = 26, bandPad = 9, groupGap = 30, rankGap = 64, inGap = 10;
  const groupsById = new Map(state.groups.map((g) => [g.id, g]));

  // 每组的带宽高
  groupsById.forEach((g) => {
    g._w = g.size * nodeSize.w + (g.size - 1) * inGap + bandPad * 2;
    g._h = nodeSize.h + bandPad * 2 + 12; // 顶部留 G# 标签
  });

  const ranks = new Map();
  groupsById.forEach((g) => {
    if (!ranks.has(g.rank)) ranks.set(g.rank, []);
    ranks.get(g.rank).push(g.id);
  });
  const maxRank = Math.max(...ranks.keys());
  const rowWidth = (ids) =>
    ids.reduce((s, id) => s + groupsById.get(id)._w, 0) + (ids.length - 1) * groupGap;
  const contentW = Math.max(...[...ranks.values()].map(rowWidth));

  // rank 1（最早）在底部：屏幕 y 随 rank 增大而减小
  const totalH = maxRank * groupsById.get(state.groups[0])._h + (maxRank - 1) * rankGap;
  const pos = new Map(); // gid -> band geometry + node anchor
  let cursorY = pad;
  for (let rank = maxRank; rank >= 1; rank--) {
    const ids = ranks.get(rank) || [];
    const g0 = groupsById.get(ids[0]);
    const rowH = g0._h;
    let x = pad + (contentW - rowWidth(ids)) / 2;
    for (const gid of ids) {
      const g = groupsById.get(gid);
      const band = { x, y: cursorY, w: g._w, h: rowH, anchors: {} };
      g.unit_ids.forEach((uid, i) => {
        const nx = x + bandPad + i * (nodeSize.w + inGap);
        const ny = cursorY + bandPad + 10;
        band.anchors[uid] = drawNode(svg, nx, ny, uid);
      });
      pos.set(gid, band);
      x += g._w + groupGap;
    }
    cursorY += rowH + rankGap;
  }

  // 共存组底带
  pos.forEach((band, gid) => {
    const g = groupsById.get(gid);
    const rect = svgEl("rect", {
      x: band.x, y: band.y, width: band.w, height: band.h,
      class: "group-band",
    });
    svg.insertBefore(rect, svg.firstChild.nextSibling); // 在箭头 defs 之后、节点之前
    if (g.size > 1) {
      svg.appendChild(
        svgEl("text", { x: band.x + bandPad, y: band.y + bandPad + 1, class: "group-label" },
          `共存组 G${gid}`)
      );
      // 组内相邻单元之间画浅金色虚线
      for (let i = 0; i < g.unit_ids.length - 1; i++) {
        const a = band.anchors[g.unit_ids[i]];
        const b = band.anchors[g.unit_ids[i + 1]];
        const y = (a.top + a.bottom) / 2;
        svg.appendChild(
          svgEl("line", {
            x1: a.cx + nodeSize.w / 2 - 2, y1: y,
            x2: b.cx - nodeSize.w / 2 + 2, y2: y,
            class: "edge-intersect",
          })
        );
      }
    }
  });

  // 组间有向边：较早组（下方）顶边 -> 较晚组（上方）底边
  const conflictRels = new Set();
  state.conflicts.forEach((c) => c.relation_ids.forEach((id) => conflictRels.add(id)));
  state.edges.forEach((e) => {
    const a = pos.get(e.from_group); // 较早
    const b = pos.get(e.to_group); // 较晚
    const x1 = a.x + a.w / 2;
    const y1 = a.y; // 顶
    const x2 = b.x + b.w / 2;
    const y2 = b.y + b.h; // 底
    const dy = Math.min(26, Math.abs(y2 - y1) / 2);
    const isConflict = e.relation_ids.some((id) => conflictRels.has(id));
    const ga = groupsById.get(e.from_group);
    const gap = groupsById.get(e.to_group).rank - ga.rank;
    svg.appendChild(
      svgEl("path", {
        d: `M${x1},${y1} C${x1},${y1 - dy} ${x2},${y2 + dy} ${x2},${y2}`,
        class: `edge ${gap > 1 ? "dim" : ""} ${isConflict ? "edge-conflict" : ""}`,
        "marker-end": isConflict ? "url(#arrowRed)" : "url(#arrow)",
      })
    );
  });

  const W = contentW + pad * 2;
  const H = totalH + pad * 2;
  svg.setAttribute("width", W).setAttribute("height", H);
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
}

/* 矛盾状态：退化为网格布局，原始关系全部画出，涉冲突关系标红 */
function drawFallback(svg) {
  const cols = Math.max(2, Math.ceil(Math.sqrt(state.units.length * 1.4)));
  const gapX = 132, gapY = 86, pad = 34;
  const pos = new Map();
  state.units.forEach((u, i) => {
    const col = i % cols, row = Math.floor(i / cols);
    const x = pad + col * gapX;
    const y = pad + row * gapY;
    pos.set(u.id, drawNode(svg, x, y, u.id));
  });

  const conflictRels = new Set();
  state.conflicts.forEach((c) => c.relation_ids.forEach((id) => conflictRels.add(id)));

  state.relations.forEach((r) => {
    const isConflict = conflictRels.has(r.id);
    const cls = isConflict
      ? "edge edge-conflict"
      : r.rel_type === "intersects"
        ? "edge-intersect"
        : "edge";
    if (r.rel_type === "intersects") {
      const a = pos.get(r.source_id), b = pos.get(r.target_id);
      if (!a || !b) return;
      svg.appendChild(
        svgEl("line", {
          x1: a.cx, y1: (a.top + a.bottom) / 2,
          x2: b.cx, y2: (b.top + b.bottom) / 2,
          class: cls,
        })
      );
    } else {
      const from = pos.get(r.from_unit), to = pos.get(r.to_unit);
      if (!from || !to) return;
      svg.appendChild(
        svgEl("line", {
          x1: from.cx, y1: (from.top + from.bottom) / 2,
          x2: to.cx, y2: (to.top + to.bottom) / 2,
          class: cls,
          "marker-end": isConflict ? "url(#arrowRed)" : "url(#arrow)",
        })
      );
    }
  });

  const rows = Math.ceil(state.units.length / cols);
  const W = pad * 2 + (cols - 1) * gapX + nodeSize.w;
  const H = pad * 2 + (rows - 1) * gapY + nodeSize.h;
  svg.setAttribute("width", W).setAttribute("height", H);
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
}

// --------------------------------------------------------------------------- //
// 推演结果
// --------------------------------------------------------------------------- //
function renderAnalysis() {
  const s = state;
  $("#stats").innerHTML = `
    <div class="stat"><div class="n">${s.units.length}</div><div class="t">地层单元</div></div>
    <div class="stat"><div class="n">${s.relations.length}</div><div class="t">录入关系</div></div>
    <div class="stat"><div class="n">${s.groups.length}</div><div class="t">共存组</div></div>
    <div class="stat"><div class="n">${s.implied_pairs}</div><div class="t">传递可推关系</div></div>
  `;

  const topo = $("#topoBox");
  if (!s.intervals_available) {
    topo.innerHTML = `
      <div class="topo-title">可行拓扑序：</div>
      <div class="no-data">存在矛盾关系，拓扑推演中止，请先消除右侧列出的冲突。</div>`;
  } else if (!s.topo_units.length) {
    topo.innerHTML = "";
  } else {
    const chips = s.topo_units
      .map(
        (gids) =>
          `<span class="topo-chip">${gids
            .map((id) => esc(unitCode(id)))
            .join("/")}</span>`
      )
      .join(`<span class="topo-sep">→</span>`);
    topo.innerHTML = `<div class="topo-title">可行拓扑序（早 → 晚）：</div><div class="topo-chain">${chips}</div>`;
  }

  const body = $("#intervalBody");
  if (!s.intervals_available) {
    body.innerHTML = `
      <tr><td colspan="5" class="no-data">
        检测到 ${s.conflicts.length} 处矛盾，无法计算层位区间
      </td></tr>`;
    return;
  }
  const rows = [...s.units].sort((a, b) =>
    a.earliest - b.earliest || a.latest - b.latest || a.id - b.id
  );
  body.innerHTML = rows
    .map((u) => {
      const aff = affectedMap.has(u.id);
      const cls = `${aff ? "affected" : ""} ${u.conflicted ? "conflicted" : ""}`;
      const judge = u.fixed
        ? `<span class="judge-fixed">层位固定</span>`
        : `<span class="judge-range">可浮动</span>`;
      return `
      <tr class="${cls}">
        <td class="code-cell">${esc(u.code)}<div class="node-name" style="color:var(--ink-soft)">${esc(u.name)}</div></td>
        <td>G${u.group_id}${u.group_members.length > 1 ? ` (${u.group_members.length})` : ""}</td>
        <td>${u.earliest}</td>
        <td>${u.latest}</td>
        <td>${judge}</td>
      </tr>`;
    })
    .join("");
}

// --------------------------------------------------------------------------- //
// 冲突详情
// --------------------------------------------------------------------------- //
function renderConflicts() {
  const box = $("#conflictBox");
  if (!state.conflicts.length) {
    box.innerHTML = `<div class="conflict-ok">✓ 未发现矛盾关系，所有时序均可自洽</div>`;
    return;
  }
  box.innerHTML = state.conflicts
    .map((c) => {
      const relBtns = c.relation_ids
        .map(
          (rid) =>
            `<button class="btn btn-mini" data-act="delrel" data-rid="${rid}"
              style="margin:2px 4px 0 0">删除关系 #${rid}</button>`
        )
        .join("");
      let chain = "";
      if (c.kind === "cycle" && c.cycle_groups) {
        chain = `<div class="crels">环上共存组：${c.cycle_groups
          .map((g) => `G${g}`)
          .join(" → ")}</div>`;
      }
      return `
      <div class="conflict-card">
        <div class="ckind">${CONFLICT_KIND_LABEL[c.kind] || c.kind}</div>
        <div class="cmsg">${esc(c.message)}</div>
        ${chain}
        <div class="crels">涉及关系：${c.relation_ids
          .map((id) => `#${id}`)
          .join("、")}</div>
        ${relBtns}
      </div>`;
    })
    .join("");
}

// --------------------------------------------------------------------------- //
// 受影响节点横幅
// --------------------------------------------------------------------------- //
function renderAffectedBanner() {
  const banner = $("#affectedBanner");
  if (!affectedMap.size) {
    banner.classList.add("hidden");
    return;
  }
  const chips = [...affectedMap.entries()]
    .map(([uid, reasons]) => {
      const title = reasons.map((r) => state.reason_labels[r] || r).join("；");
      return `<span class="affected-chip" title="${esc(title)}">${esc(
        unitCode(uid)
      )}</span>`;
    })
    .join("");
  banner.innerHTML = `<b>本次操作受影响节点（${affectedMap.size}）：</b>${chips}
    <div class="node-name" style="margin-top:3px">悬停节点 / 徽章查看具体变化原因</div>`;
  banner.classList.remove("hidden");
}

// --------------------------------------------------------------------------- //
// 交互
// --------------------------------------------------------------------------- //
let toastTimer = null;
function toast(msg, kind = "") {
  const t = $("#toast");
  t.textContent = msg;
  t.className = `toast ${kind}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), 3600);
}

$("#unitForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  try {
    const next = await api("/api/units", {
      method: "POST",
      body: JSON.stringify(Object.fromEntries(fd)),
    });
    applyState(next);
    e.target.reset();
    e.target.querySelector('[name="kind"]').value = "layer";
    toast(`单元 ${next.units.at(-1).code} 已录入`, "success");
  } catch (err) {
    toast(err.message, "error");
  }
});

$("#relForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const payload = {
    source_id: Number(fd.get("source_id")),
    target_id: Number(fd.get("target_id")),
    rel_type: fd.get("rel_type"),
    note: fd.get("note") || "",
  };
  if (!payload.source_id || !payload.target_id) {
    toast("请先选择关系两端的单元", "error");
    return;
  }
  try {
    const next = await api("/api/relations", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    applyState(next);
    e.target.querySelector('[name="note"]').value = "";
    if (!next.consistent) {
      toast(`关系已添加，但检测到 ${next.conflicts.length} 处矛盾，请查看冲突详情`, "error");
    } else {
      const n = (next.affected || []).filter(
        (a) => !a.reasons.includes("new_unit")
      ).length;
      toast(`关系已建立，${n} 个节点推演结果受影响`, "success");
    }
  } catch (err) {
    toast(err.message, "error");
  }
});

$("#unitList").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-act]");
  if (!btn) return;
  const li = e.target.closest("li[data-uid]");
  const uid = Number(li.dataset.uid);
  const act = btn.dataset.act;
  if (act === "src" || act === "dst") {
    const name = act === "src" ? "source_id" : "target_id";
    $("#relForm").querySelector(`[name="${name}"]`).value = uid;
    toast(`${unitCode(uid)} 已设为${act === "src" ? "起点（A）" : "终点（B）"}`);
  } else if (act === "del") {
    if (!confirm(`确认删除单元 ${unitCode(uid)}？其相关关系将一并删除。`)) return;
    api(`/api/units/${uid}`, { method: "DELETE" })
      .then(applyState)
      .then(() => toast("单元及相关关系已删除"))
      .catch((err) => toast(err.message, "error"));
  }
});

function deleteRelation(rid) {
  if (!confirm(`确认删除关系 #${rid}？`)) return;
  api(`/api/relations/${rid}`, { method: "DELETE" })
    .then(applyState)
    .then(() => toast(`关系 #${rid} 已删除，推演结果已更新`))
    .catch((err) => toast(err.message, "error"));
}

$("#relList").addEventListener("click", (e) => {
  const btn = e.target.closest('button[data-act="delrel"]');
  if (btn) deleteRelation(Number(btn.dataset.rid));
});
$("#conflictBox").addEventListener("click", (e) => {
  const btn = e.target.closest('button[data-act="delrel"]');
  if (btn) deleteRelation(Number(btn.dataset.rid));
});

$("#btnDemo").addEventListener("click", async () => {
  try {
    applyState(await api("/api/reset/demo", { method: "POST" }));
    toast("示例发掘区数据已载入：10 个单元、10 条关系", "success");
  } catch (err) {
    toast(err.message, "error");
  }
});

$("#btnClear").addEventListener("click", async () => {
  if (!confirm("确认清空全部单元与关系？此操作不可恢复。")) return;
  try {
    applyState(await api("/api/reset/clear", { method: "POST" }));
    toast("已清空");
  } catch (err) {
    toast(err.message, "error");
  }
});

$("#btnExport").addEventListener("click", () => {
  window.location.href = "/api/export";
});

refresh().catch((err) => toast("初始化失败：" + err.message, "error"));
