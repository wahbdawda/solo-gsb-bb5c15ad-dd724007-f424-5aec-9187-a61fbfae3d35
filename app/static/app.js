/* 考古地层关系推演台 —— 前端逻辑（原生 JS，零依赖） */
"use strict";

const KIND_TEXT = {
  earlier_than: "早于",
  later_than: "晚于",
  intersects: "相交",
};

let state = { units: [], relations: [], analysis: null, affected: [] };
let selectedId = null;

const $ = (sel) => document.querySelector(sel);
const svgNS = "http://www.w3.org/2000/svg";

// ------------------------------------------------------------------
// API
// ------------------------------------------------------------------

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let msg = `请求失败（${res.status}）`;
    try {
      const data = await res.json();
      if (data.detail) msg = data.detail;
    } catch (_) {}
    throw new Error(msg);
  }
  return res.json();
}

async function refresh() {
  state = await api("/api/state");
  selectedId = null;
  render();
}

function showFlash(msg, type = "error", timeout = 4000) {
  const el = $("#flash");
  el.textContent = msg;
  el.className = `flash ${type === "error" ? "" : type}`;
  clearTimeout(showFlash._t);
  if (timeout) showFlash._t = setTimeout(() => el.classList.add("hidden"), timeout);
}

// ------------------------------------------------------------------
// 渲染
// ------------------------------------------------------------------

function render() {
  renderSelects();
  renderUnitList();
  renderRelationList();
  renderGraph();
  renderConflicts();
  renderSummary();
}

function renderSelects() {
  const opts =
    '<option value="">请选择…</option>' +
    state.units.map((u) => `<option value="${u.id}">${u.id} · ${escapeHtml(u.name)}</option>`).join("");
  document.querySelectorAll('#form-relation select[name$="_id"]').forEach((s) => {
    const prev = s.value;
    s.innerHTML = opts;
    if (prev && state.units.some((u) => u.id === prev)) s.value = prev;
  });
}

function renderUnitList() {
  const ul = $("#unit-list");
  if (!state.units.length) {
    ul.innerHTML = '<li class="empty-hint" style="position:static">还没有地层单元</li>';
    return;
  }
  const conflictSet = new Set(state.analysis.conflict_unit_ids);
  const affectedSet = new Set(state.affected);
  ul.innerHTML = state.units
    .map((u) => {
      const iv = state.analysis.intervals[u.id];
      const classes = ["unit-item"];
      if (conflictSet.has(u.id)) classes.push("is-conflict");
      if (affectedSet.has(u.id)) classes.push("is-affected");
      if (selectedId === u.id) classes.push("selected");
      const badge = conflictSet.has(u.id)
        ? '<span class="badge badge-conflict">冲突</span>'
        : affectedSet.has(u.id)
        ? '<span class="badge badge-affected">受影响</span>'
        : "";
      const ivBadge = iv
        ? ` <span class="badge badge-interval">${iv.earliest === iv.latest ? iv.earliest : iv.earliest + "–" + iv.latest}</span>`
        : "";
      return `<li class="${classes.join(" ")}" data-id="${u.id}" data-pick="${u.id}">
        <div class="unit-main">
          <div><span class="unit-id">${u.id}</span>${badge}${ivBadge}</div>
          <div class="unit-name">${escapeHtml(u.name)}</div>
          ${u.note ? `<div class="unit-note" title="${escapeHtml(u.note)}">${escapeHtml(u.note)}</div>` : ""}
        </div>
        <button class="btn-danger" data-del-unit="${u.id}" title="删除该单元（关联关系一并删除）">✕</button>
      </li>`;
    })
    .join("");
}

function renderRelationList() {
  const ul = $("#relation-list");
  if (!state.relations.length) {
    ul.innerHTML = '<li class="empty-hint" style="position:static">还没有关系</li>';
    return;
  }
  const conflictRels = new Set(state.analysis.conflict_relation_ids);
  const unitName = Object.fromEntries(state.units.map((u) => [u.id, u.name]));
  ul.innerHTML = state.relations
    .map((r) => {
      const cls = conflictRels.has(r.id) ? "rel-item is-conflict" : "rel-item";
      const kindCls = r.kind === "intersects" ? "intersects" : "temporal";
      return `<li class="${cls}">
        <div class="rel-text">
          <span class="uid" data-pick="${r.source_id}">${r.source_id}</span>
          <span class="rel-kind ${kindCls}">${KIND_TEXT[r.kind]}</span>
          <span class="uid" data-pick="${r.target_id}">${r.target_id}</span>
          ${conflictRels.has(r.id) ? '<span class="badge badge-conflict">矛盾关系</span>' : ""}
          ${r.note ? `<div class="rel-note">${escapeHtml(r.note)}</div>` : ""}
        </div>
        <button class="btn-danger" data-del-rel="${r.id}" title="删除关系">✕</button>
      </li>`;
    })
    .join("");
}

function renderConflicts() {
  const box = $("#conflict-box");
  const conflicts = state.analysis.conflicts || [];
  if (!conflicts.length) {
    box.classList.add("hidden");
    box.innerHTML = "";
    return;
  }
  box.classList.remove("hidden");
  box.innerHTML =
    `<h3>⚠ 检测到 ${conflicts.length} 处矛盾，层位推演已暂停（删除标红关系即可恢复）</h3>` +
    conflicts
      .map(
        (c, i) => `<div class="conflict-item" data-conflict-idx="${i}">
          <div>${i + 1}. ${escapeHtml(c.message)}</div>
          <div class="conflict-cycle">涉及单元：${c.cycle.map(escapeHtml).join(" → ")}</div>
        </div>`
      )
      .join("");
}

function renderSummary() {
  const el = $("#interval-summary");
  const a = state.analysis;
  if (!state.units.length) {
    el.innerHTML = "";
    return;
  }
  if (a.has_conflict) {
    el.innerHTML =
      '<strong style="color:var(--red)">存在矛盾环</strong>：地层单元的早晚关系不自洽，' +
      "无法得到可行的层位顺序，请先解除冲突。";
    return;
  }
  const groups = a.components.filter((c) => c.members.length > 1).length;
  el.innerHTML =
    `推演通过：共 <strong>${a.total_levels}</strong> 个层位，` +
    `${state.units.length} 个单元归并为 ${a.components.length} 个堆积单位` +
    (groups ? `（其中 ${groups} 个相交同期组）` : "") +
    "。区间 [最早–最晚] 表示该单元在所有可行拓扑序中可能出现的层位范围。";
}

// ------------------------------------------------------------------
// SVG 关系图
// ------------------------------------------------------------------

const NODE_W = 78;
const NODE_H = 46;
const MEM_GAP = 10;
const COL_GAP = 46;
const ROW_H = 96;
const MARGIN = 34;
const PAD = 14;

function renderGraph() {
  const svg = $("#graph");
  svg.innerHTML = "";
  $("#graph-empty").classList.toggle("hidden", state.units.length > 0);
  if (!state.units.length) {
    svg.setAttribute("width", 10);
    svg.setAttribute("height", 10);
    return;
  }

  const a = state.analysis;
  const conflictUnits = new Set(a.conflict_unit_ids);
  const conflictRels = new Set(a.conflict_relation_ids);
  const affectedSet = new Set(state.affected);

  // 组件 -> 布局框；每个单元 -> 中心点
  const compBox = {};
  const nodePos = {};

  const comps = a.components;
  const groupW = (c) => c.members.length * NODE_W + (c.members.length - 1) * MEM_GAP + PAD * 2;
  const groupH = NODE_H + PAD * 2;

  if (a.has_conflict) {
    // 冲突时按网格排布全部共存组（层位关系此时无意义）
    const perRow = 3;
    const rows = [];
    comps.forEach((c, i) => {
      const r = Math.floor(i / perRow);
      (rows[r] = rows[r] || []).push(c);
    });
    let y = MARGIN;
    rows.forEach((row) => {
      let x = MARGIN;
      row.forEach((c) => {
        placeComponent(c, x, y, compBox, nodePos);
        x += groupW(c) + COL_GAP;
      });
      y += groupH + ROW_H * 0.55;
    });
  } else {
    // 无冲突：按最早可能层位分列（位置 1 在最下方，符合地层剖面习惯）。
    // 拓扑位置可能有空档（菱形结构中中间单位可浮动），空档行压缩不显示。
    const byLevel = {};
    comps.forEach((c) => {
      (byLevel[c.level] = byLevel[c.level] || []).push(c);
    });
    Object.values(byLevel).forEach((row) => row.sort((x, y) => x.id.localeCompare(y.id)));
    const usedLevels = Object.keys(byLevel).map(Number).sort((a, b) => a - b);

    const maxRowW = Math.max(
      ...usedLevels.map(
        (lvl) =>
          byLevel[lvl].reduce((s, c) => s + groupW(c), 0) +
          (byLevel[lvl].length - 1) * COL_GAP
      )
    );
    const total = usedLevels.length;
    usedLevels.forEach((lvl, visualIdx) => {
      const row = byLevel[lvl];
      const rowW =
        row.reduce((s, c) => s + groupW(c), 0) + Math.max(0, row.length - 1) * COL_GAP;
      let x = MARGIN + Math.max(0, (maxRowW - rowW) / 2);
      // 最早位置在底部
      const y = MARGIN + (total - 1 - visualIdx) * ROW_H;
      row.forEach((c) => {
        placeComponent(c, x, y, compBox, nodePos);
        x += groupW(c) + COL_GAP;
      });
    });
  }

  // 画布尺寸
  const allBoxes = Object.values(compBox);
  const width = Math.max(...allBoxes.map((b) => b.x + b.w)) + MARGIN;
  const height = Math.max(...allBoxes.map((b) => b.y + b.h)) + MARGIN + 12;
  svg.setAttribute("width", width);
  svg.setAttribute("height", height);

  // 层位色带与标注（仅无冲突时；按压缩后的可视行绘制，作为背景先入图）
  let usedLevels = [];
  if (!a.has_conflict) {
    usedLevels = [...new Set(comps.map((c) => c.level))].sort((x, y) => x - y);
    usedLevels.forEach((lvl, visualIdx) => {
      const y = MARGIN + (usedLevels.length - 1 - visualIdx) * ROW_H - PAD;
      svg.appendChild(
        svgEl("rect", { x: 0, y, width, height: ROW_H, class: "level-band" })
      );
      svg.appendChild(
        svgEl("text", { x: 14, y: y + 16, class: "level-label" }, `层位 ${lvl}`)
      );
    });
  }

  // 箭头定义（普通 / 矛盾两种颜色）
  const defs = svgEl("defs");
  defs.innerHTML = `
    <marker id="arrow" markerWidth="9" markerHeight="9" refX="8" refY="3.2"
            orient="auto" markerUnits="userSpaceOnUse">
      <path d="M0,0 L8,3.2 L0,6.4 Z" fill="#2f5d8a"></path>
    </marker>
    <marker id="arrow-conflict" markerWidth="9" markerHeight="9" refX="8" refY="3.2"
            orient="auto" markerUnits="userSpaceOnUse">
      <path d="M0,0 L8,3.2 L0,6.4 Z" fill="#c0392b"></path>
    </marker>`;
  svg.appendChild(defs);

  const unitComp = {};
  comps.forEach((c) => c.members.forEach((m) => (unitComp[m] = c.id)));

  // 相交关系：同组内成员之间画虚线
  state.relations
    .filter((r) => r.kind === "intersects")
    .forEach((r) => {
      const p = nodePos[r.source_id];
      const q = nodePos[r.target_id];
      if (!p || !q) return;
      svg.appendChild(
        svgEl("line", {
          x1: p.x + NODE_W / 2,
          y1: p.y + NODE_H / 2,
          x2: q.x + NODE_W / 2,
          y2: q.y + NODE_H / 2,
          class: "edge-intersect",
        })
      );
    });

  // 早晚关系边
  state.relations
    .filter((r) => r.kind !== "intersects")
    .forEach((r) => {
      const [fromId, toId] =
        r.kind === "earlier_than" ? [r.source_id, r.target_id] : [r.target_id, r.source_id];
      const cbFrom = compBox[unitComp[fromId]];
      const cbTo = compBox[unitComp[toId]];
      if (!cbFrom || !cbTo) return;
      const isConflict = conflictRels.has(r.id);
      // 起点：早者框顶；终点：晚者框底（无冲突分层时天然向上）
      const x1 = cbFrom.x + cbFrom.w / 2;
      const y1 = cbFrom.y;
      const x2 = cbTo.x + cbTo.w / 2;
      const y2 = cbTo.y + cbTo.h;
      const d = `M ${x1} ${y1} C ${x1} ${y1 - 40}, ${x2} ${y2 + 40}, ${x2} ${y2}`;
      svg.appendChild(
        svgEl("path", {
          d,
          class: isConflict ? "edge-conflict" : "edge-time",
          "marker-end": isConflict ? "url(#arrow-conflict)" : "url(#arrow)",
        })
      );
    });

  // 共存组框 + 单元节点
  const nameOf = Object.fromEntries(state.units.map((u) => [u.id, u.name]));
  comps.forEach((c) => {
    const b = compBox[c.id];
    const inConflict = c.members.some((m) => conflictUnits.has(m));
    if (c.members.length > 1) {
      svg.appendChild(
        svgEl("rect", {
          x: b.x,
          y: b.y,
          width: b.w,
          height: b.h,
          rx: 9,
          fill: "rgba(185,119,14,0.06)",
          stroke: inConflict ? "var(--red)" : "var(--amber)",
          "stroke-width": 1.2,
          "stroke-dasharray": "6 4",
        })
      );
      svg.appendChild(
        svgEl(
          "text",
          { x: b.x + 7, y: b.y + 12, "font-size": 9.5, fill: "var(--amber)" },
          "相交同期"
        )
      );
    }
    c.members.forEach((m) => {
      const p = nodePos[m];
      drawNode(svg, m, nameOf[m], p, {
        conflict: conflictUnits.has(m),
        affected: affectedSet.has(m),
        selected: selectedId === m,
        interval: state.analysis.intervals[m],
      });
    });
  });

  // 绑定节点点击
  svg.querySelectorAll("g.graph-node").forEach((g) =>
    g.addEventListener("click", () => selectUnit(g.dataset.id))
  );
}

function placeComponent(c, x, y, compBox, nodePos) {
  const w = c.members.length * NODE_W + (c.members.length - 1) * MEM_GAP + PAD * 2;
  const h = NODE_H + PAD * 2;
  compBox[c.id] = { x, y, w, h };
  c.members.forEach((m, i) => {
    nodePos[m] = { x: x + PAD + i * (NODE_W + MEM_GAP), y: y + PAD };
  });
}

function drawNode(svg, id, name, p, opts) {
  const g = svgEl("g", { class: "graph-node", "data-id": id });
  const cls = ["node-rect"];
  if (opts.conflict) cls.push("conflict");
  if (opts.affected) cls.push("affected");
  if (opts.selected) cls.push("selected");
  g.appendChild(svgEl("rect", { x: p.x, y: p.y, width: NODE_W, height: NODE_H, class: cls.join(" ") }));
  g.appendChild(svgEl("text", { x: p.x + NODE_W / 2, y: p.y + 17, class: "node-id" }, id));
  g.appendChild(
    svgEl(
      "text",
      { x: p.x + NODE_W / 2, y: p.y + 31, class: "node-name" },
      truncate(name, 7)
    )
  );
  if (opts.interval) {
    const iv = opts.interval;
    const label = iv.earliest === iv.latest ? `层 ${iv.earliest}` : `层 ${iv.earliest}~${iv.latest}`;
    g.appendChild(svgEl("text", { x: p.x + NODE_W / 2, y: p.y + 42.5, class: "node-interval" }, label));
  }
  g.appendChild(svgEl("title", {}, `${id} · ${name}`));
  svg.appendChild(g);
}

function svgEl(tag, attrs = {}, text) {
  const el = document.createElementNS(svgNS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  if (text !== undefined) el.textContent = text;
  return el;
}

// ------------------------------------------------------------------
// 交互
// ------------------------------------------------------------------

function selectUnit(id) {
  selectedId = selectedId === id ? null : id;
  render();
  if (selectedId) {
    const li = document.querySelector(`.unit-item[data-id="${cssEscape(selectedId)}"]`);
    if (li) li.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
}

async function submitUnit(e) {
  e.preventDefault();
  const fd = new FormData(e.target);
  try {
    const data = await api("/api/units", {
      method: "POST",
      body: JSON.stringify({
        id: fd.get("id").trim(),
        name: fd.get("name").trim(),
        note: fd.get("note").trim(),
      }),
    });
    state = data;
    render();
    e.target.reset();
    showFlash(`单元 ${data.affected[0] || ""} 已添加（受影响节点已标出）。`, "info");
  } catch (err) {
    showFlash(err.message);
  }
}

async function submitRelation(e) {
  e.preventDefault();
  const fd = new FormData(e.target);
  const payload = {
    kind: fd.get("kind"),
    source_id: fd.get("source_id"),
    target_id: fd.get("target_id"),
    note: fd.get("note").trim(),
  };
  try {
    const data = await api("/api/relations", { method: "POST", body: JSON.stringify(payload) });
    state = data;
    selectedId = null;
    render();
    if (data.analysis.has_conflict) {
      showFlash("关系已保存，但形成矛盾环！冲突节点与关系已标红，受影响节点为橙色描边。", "warn", 7000);
    } else {
      showFlash(
        `关系已添加。受影响节点：${data.affected.join("、")}（层位区间已重新推演）。`,
        "info"
      );
    }
  } catch (err) {
    showFlash(err.message);
  }
}

async function deleteUnit(id) {
  if (!confirm(`确定删除单元 ${id}？与之关联的全部关系将一并删除。`)) return;
  try {
    const data = await api(`/api/units/${encodeURIComponent(id)}`, { method: "DELETE" });
    state = data;
    if (selectedId === id) selectedId = null;
    render();
    showFlash(`单元 ${id} 已删除，受影响节点已标出。`, "info");
  } catch (err) {
    showFlash(err.message);
  }
}

async function deleteRelation(id) {
  try {
    const data = await api(`/api/relations/${id}`, { method: "DELETE" });
    state = data;
    render();
    showFlash(`关系 #${id} 已删除，受影响节点已标出。`, "info");
  } catch (err) {
    showFlash(err.message);
  }
}

async function exportJson() {
  try {
    const res = await fetch("/api/export");
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "strata_export.json";
    a.click();
    URL.revokeObjectURL(url);
  } catch (err) {
    showFlash("导出失败：" + err.message);
  }
}

async function loadSample() {
  if (state.units.length && !confirm("载入示例将清空当前全部数据，是否继续？")) return;
  try {
    state = await api("/api/sample", { method: "POST" });
    selectedId = null;
    render();
    showFlash("示例数据已载入：7 个地层单元、含一组相交同期堆积。", "info");
  } catch (err) {
    showFlash(err.message);
  }
}

async function resetAll() {
  if (!confirm("确定清空全部地层单元与关系？此操作不可恢复。")) return;
  try {
    state = await api("/api/reset", { method: "POST" });
    selectedId = null;
    render();
  } catch (err) {
    showFlash(err.message);
  }
}

// ------------------------------------------------------------------
// 工具
// ------------------------------------------------------------------

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));
}
function truncate(s, n) {
  return s.length > n ? s.slice(0, n) + "…" : s;
}
function cssEscape(s) {
  return window.CSS && CSS.escape ? CSS.escape(s) : s.replace(/"/g, '\\"');
}

// ------------------------------------------------------------------
// 初始化
// ------------------------------------------------------------------

document.addEventListener("click", (e) => {
  const delU = e.target.closest("[data-del-unit]");
  if (delU) return deleteUnit(delU.dataset.delUnit);
  const delR = e.target.closest("[data-del-rel]");
  if (delR) return deleteRelation(delR.dataset.delRel);
  const pick = e.target.closest("[data-pick]");
  if (pick) return selectUnit(pick.dataset.pick);
  const cf = e.target.closest("[data-conflict-idx]");
  if (cf) {
    const c = state.analysis.conflicts[+cf.dataset.conflictIdx];
    selectedId = c.cycle[0];
    render();
    return;
  }
});

$("#form-unit").addEventListener("submit", submitUnit);
$("#form-relation").addEventListener("submit", submitRelation);
$("#btn-export").addEventListener("click", exportJson);
$("#btn-sample").addEventListener("click", loadSample);
$("#btn-reset").addEventListener("click", resetAll);

refresh().catch((err) => showFlash(err.message));
