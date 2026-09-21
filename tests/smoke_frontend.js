/* 前端渲染冒烟测试：用极简 DOM 桩执行 app.js 的 render()，
   覆盖无冲突（分层图）与有冲突（网格图）两种状态。 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

function makeEl(tag) {
  const el = {
    tagName: String(tag || "div").toUpperCase(),
    children: [],
    attributes: {},
    style: {},
    dataset: {},
    classList: {
      _set: new Set(),
      add(...c) { c.forEach((x) => this._set.add(x)); },
      remove(...c) { c.forEach((x) => this._set.delete(x)); },
      toggle(c, force) { force ? this.add(c) : this.remove(c); },
      contains(c) { return this._set.has(c); },
    },
    _innerHTML: "",
    set innerHTML(v) { this._innerHTML = v; this.children = []; },
    get innerHTML() { return this._innerHTML; },
    set textContent(v) { this._innerHTML = String(v); },
    get textContent() { return this._innerHTML; },
    set className(v) { this.classList._set = new Set(String(v).split(/\s+/).filter(Boolean)); },
    appendChild(child) { this.children.push(child); child.parentNode = this; return child; },
    insertBefore(child) { this.children.push(child); return child; },
    setAttribute(k, v) { this.attributes[k] = String(v); if (k === "class") this.className = v; if (k.startsWith("data-")) this.dataset[k.slice(5)] = String(v); },
    getAttribute(k) { return this.attributes[k]; },
    addEventListener() {},
    querySelectorAll() { return []; },
    querySelector() { return null; },
    scrollIntoView() {},
    closest() { return null; },
  };
  return el;
}

const elements = {};
function $(sel) {
  if (!elements[sel]) {
    const tag = sel === "svg" || sel === "#graph" ? "svg" : "div";
    elements[sel] = makeEl(tag);
  }
  return elements[sel];
}

const documentStub = {
  querySelector: (sel) => $(sel),
  querySelectorAll: () => [],
  createElement: (tag) => makeEl(tag),
  createElementNS: (ns, tag) => makeEl(tag),
  addEventListener: () => {},
  title: "",
};

const sandbox = {
  document: documentStub,
  window: {},
  fetch: async () => { throw new Error("no fetch in smoke test"); },
  confirm: () => true,
  CSS: { escape: (s) => s },
  console,
  setTimeout, clearTimeout,
};
sandbox.window.CSS = sandbox.CSS;
vm.createContext(sandbox);

const code = fs.readFileSync(path.join(__dirname, "..", "app", "static", "app.js"), "utf8");
vm.runInContext(code, sandbox);

// 构造与后端 analyze 输出同构的两种状态
function stateFor(conflict) {
  const units = ["U1", "U2", "U3", "U4", "U5", "U6", "U7"].map((id) => ({
    id, name: "单元" + id, note: "",
  }));
  const relations = [
    { id: 1, kind: "earlier_than", source_id: "U1", target_id: "U2", note: "" },
    { id: 2, kind: "intersects", source_id: "U2", target_id: "U3", note: "" },
    { id: 3, kind: "earlier_than", source_id: "U2", target_id: "U4", note: "" },
    { id: 4, kind: "earlier_than", source_id: "U3", target_id: "U5", note: "" },
    { id: 5, kind: "earlier_than", source_id: "U4", target_id: "U5", note: "" },
    { id: 6, kind: "earlier_than", source_id: "U5", target_id: "U6", note: "" },
    { id: 7, kind: "earlier_than", source_id: "U6", target_id: "U7", note: "" },
  ];
  if (conflict) relations.push({ id: 8, kind: "earlier_than", source_id: "U7", target_id: "U1", note: "" });
  return { units, relations, analysis: analysis(conflict) };
}

function analysis(conflict) {
  if (!conflict) {
    return {
      has_conflict: false,
      conflicts: [],
      conflict_unit_ids: [],
      conflict_relation_ids: [],
      components: [
        { id: "U1", members: ["U1"], level: 1 },
        { id: "U2", members: ["U2", "U3"], level: 2 },
        { id: "U4", members: ["U4"], level: 3 },
        { id: "U5", members: ["U5"], level: 4 },
        { id: "U6", members: ["U6"], level: 5 },
        { id: "U7", members: ["U7"], level: 6 },
      ],
      total_levels: 6,
      intervals: {
        U1: { earliest: 1, latest: 1 },
        U2: { earliest: 2, latest: 2 }, U3: { earliest: 2, latest: 2 },
        U4: { earliest: 3, latest: 3 }, U5: { earliest: 4, latest: 4 },
        U6: { earliest: 5, latest: 5 }, U7: { earliest: 6, latest: 6 },
      },
    };
  }
  return {
    has_conflict: true,
    conflicts: [{ type: "cyclic_order", message: "闭环测试", cycle: ["U1", "U2", "U3", "U4", "U5", "U6", "U7"], relation_ids: [1, 3, 4, 5, 6, 7, 8] }],
    conflict_unit_ids: ["U1", "U2", "U3", "U4", "U5", "U6", "U7"],
    conflict_relation_ids: [1, 3, 4, 5, 6, 7, 8],
    components: [
      { id: "U1", members: ["U1"], level: null },
      { id: "U2", members: ["U2", "U3"], level: null },
      { id: "U4", members: ["U4"], level: null },
      { id: "U5", members: ["U5"], level: null },
      { id: "U6", members: ["U6"], level: null },
      { id: "U7", members: ["U7"], level: null },
    ],
    total_levels: 0,
    intervals: Object.fromEntries(["U1", "U2", "U3", "U4", "U5", "U6", "U7"].map((u) => [u, null])),
  };
}

for (const conflict of [false, true]) {
  const st = stateFor(conflict);
  st.analysis = analysis(conflict);
  st.affected = conflict ? ["U1", "U7"] : ["U4"];
  vm.runInContext(`
    state = ${JSON.stringify(JSON.stringify(st))};
    state = JSON.parse(state);
    render();
  `, sandbox);

  const graph = sandbox.document.querySelector("#graph");
  const nodes = graph.children.filter((c) => c.tagName === "G");
  const rects = graph.children.filter((c) => c.tagName === "RECT");
  // 至少包含 6 个层位色带（无冲突）或 0 个（冲突），以及 7 个节点组
  if (!conflict) {
    if (nodes.length !== 7) throw new Error(`无冲突：期望 7 个节点 g，实际 ${nodes.length}`);
    const bands = rects.filter((r) => (r.attributes.class || "") === "level-band");
    if (bands.length !== 6) throw new Error(`无冲突：期望 6 条层位色带，实际 ${bands.length}`);
    const width = Number(graph.attributes.width);
    if (!(width >= 200)) throw new Error("图宽度异常: " + width);
  } else {
    if (nodes.length !== 7) throw new Error(`冲突：期望 7 个节点 g，实际 ${nodes.length}`);
  }
  const conflictBox = sandbox.document.querySelector("#conflict-box");
  if (!conflict) {
    if (!conflictBox.classList.contains("hidden")) throw new Error("无冲突时冲突框应隐藏");
  } else {
    if (conflictBox.classList.contains("hidden")) throw new Error("冲突时冲突框应显示");
    if (!conflictBox.innerHTML.includes("闭环测试")) throw new Error("冲突详情未渲染");
  }
  const unitList = sandbox.document.querySelector("#unit-list");
  if (!unitList.innerHTML.includes("U4")) throw new Error("单元列表未渲染");
  const summary = sandbox.document.querySelector("#interval-summary");
  if (!summary.innerHTML) throw new Error("汇总信息未渲染");
  console.log(`${conflict ? "冲突" : "无冲突"}状态渲染 OK：节点 ${nodes.length}，` +
    `冲突框${conflictBox.classList.contains("hidden") ? "隐藏" : "显示"}`);
}

// 工具函数
const esc = vm.runInContext(`escapeHtml('<a>&"x"')`, sandbox);
if (esc !== "&lt;a&gt;&amp;&quot;x&quot;") throw new Error("escapeHtml 错误: " + esc);
const tr = vm.runInContext(`truncate("abcdefgh", 7)`, sandbox);
if (tr !== "abcdefg…") throw new Error("truncate 错误: " + tr);
console.log("工具函数 OK");
console.log("\n前端渲染冒烟测试全部通过 ✔");
