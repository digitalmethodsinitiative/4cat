/* Processor catalogue (prototype).
 *
 * A thin reactive client over the /api/processor-map/* endpoints: browse/search
 * processors, then open one to see "how to run this" (what dataset it accepts and
 * concrete ways to get there from a data source) and "what can run on this" (the
 * follow-up processors and filters its output unlocks). Holds no compatibility
 * logic itself -- that all lives in common/lib/processor_map.py.
 */
(function () {
  "use strict";

  const API = "/api/processor-map";
  let CATALOGUE = [];
  const TITLE = {};

  const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g,
    c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const titleOf = t => TITLE[t] || t;
  const listOf = v => Array.isArray(v) ? v.join(", ") : String(v);

  async function getJSON(url) {
    const response = await fetch(url);
    if (!response.ok) throw new Error("HTTP " + response.status);
    return response.json();
  }

  async function init() {
    let data;
    try {
      data = await getJSON(`${API}/catalogue`);
    } catch (e) {
      document.getElementById("pc-loading").textContent = "Could not load processors.";
      return;
    }
    CATALOGUE = (data.processors || []).slice().sort((a, b) => (a.title || a.type).localeCompare(b.title || b.type));
    CATALOGUE.forEach(p => { TITLE[p.type] = p.title || p.type; });

    populateCategories();
    document.getElementById("pc-search").addEventListener("input", renderCatalogue);
    document.getElementById("pc-category").addEventListener("change", renderCatalogue);
    renderCatalogue();
  }

  function populateCategories() {
    const categories = [...new Set(CATALOGUE.map(p => p.category || "(uncategorised)"))].sort();
    const select = document.getElementById("pc-category");
    categories.forEach(category => {
      const option = document.createElement("option");
      option.value = category;
      option.textContent = category;
      select.appendChild(option);
    });
  }

  // --- catalogue (browse / search) ---

  function renderCatalogue() {
    const query = document.getElementById("pc-search").value.trim().toLowerCase();
    const category = document.getElementById("pc-category").value;

    let items = CATALOGUE;
    if (category) items = items.filter(p => (p.category || "(uncategorised)") === category);
    if (query) items = items.filter(p =>
      `${p.type} ${p.title || ""} ${p.category || ""} ${p.description || ""}`.toLowerCase().includes(query));

    const groups = {};
    items.forEach(p => { const c = p.category || "(uncategorised)"; (groups[c] = groups[c] || []).push(p); });

    const section = document.getElementById("pc-catalogue");
    section.innerHTML = items.length
      ? Object.keys(groups).sort().map(c =>
          `<div class="pc-cat"><h2><span>${esc(c)}</span></h2><div class="pc-grid">${groups[c].map(card).join("")}</div></div>`
        ).join("")
      : '<p class="banner">No processors match your search.</p>';
    document.getElementById("pc-count").textContent = `${items.length} of ${CATALOGUE.length}`;
    section.querySelectorAll(".pc-card").forEach(el => el.addEventListener("click", () => showDetail(el.dataset.type)));
  }

  function card(p) {
    const badges = [
      p.is_datasource ? '<span class="inline-label property-badge pc-source">data source</span>' : "",
      p.is_filter ? '<span class="inline-label property-badge pc-filter">filter</span>' : "",
      p.has_override ? '<span class="inline-label property-badge pc-approx">override</span>' : ""
    ].join("");
    return `<button class="pc-card" data-type="${esc(p.type)}">
      <div class="pc-card-head"><h4>${esc(p.title || p.type)}</h4><span class="pc-badges">${badges}</span></div>
      <p class="pc-desc">${esc(p.description || "")}</p>
    </button>`;
  }

  // --- detail ("how to run this" / "what can run on this") ---

  async function showDetail(type) {
    const body = document.getElementById("pc-detail-body");
    body.innerHTML = '<p class="banner">Loading…</p>';
    window.scrollTo({ top: 0, behavior: "smooth" });
    let info;
    try {
      info = await getJSON(`${API}/processor/${encodeURIComponent(type)}`);
    } catch (e) {
      body.innerHTML = '<p class="banner">Could not load this processor.</p>';
      return;
    }
    if (!info || !info.type) {
      body.innerHTML = '<p class="banner">Processor not found.</p>';
      return;
    }
    body.innerHTML = detailHtml(info);
    body.querySelectorAll("[data-type]").forEach(el =>
      el.addEventListener("click", e => { e.stopPropagation(); showDetail(el.dataset.type); }));
    body.querySelectorAll(".pc-more").forEach(el =>
      el.addEventListener("click", () => {
        const hidden = el.previousElementSibling;   // the wrap of overflow chips
        if (hidden) hidden.hidden = false;
        el.remove();
      }));
  }

  // a row of clickable chips linking to other processors. `steps` are objects
  // carrying at least a `type`; a "maybe" certainty is shown as an unconfirmed chip.
  function chipRow(steps, cls) {
    if (!steps || !steps.length) return '<span class="pc-muted">none</span>';
    return '<div class="pc-chips">' + steps.map(step => {
      const maybe = step.certainty === "maybe";
      const marker = maybe ? ' <span class="pc-q">?</span>' : "";
      const tip = maybe ? ' title="might apply — not confirmed from the specs alone"' : "";
      return `<button class="pc-chip ${cls || ""}${maybe ? " pc-uncertain" : ""}" data-type="${esc(step.type)}"${tip}>`
        + `${esc(titleOf(step.type))}${marker}</button>`;
    }).join("") + "</div>";
  }

  // the declared requirement (from describe_spec) as plain, non-clickable chips
  const REQ_LABEL = {
    types: v => `type is ${listOf(v)}`,
    type_prefixes: v => `type starts with ${listOf(v)}`,
    media_types: v => `media is ${listOf(v)}`,
    datasources: v => `from data source ${listOf(v)}`,
    is_collector: () => "must be a data source",
    extensions: v => `format is ${listOf(v)}`,
    top_dataset_only: () => "top-level dataset only",
    child_only: () => "must be a derived dataset",
    excluded_types: v => `not ${listOf(v)}`,
    rankable: v => v ? "must be rankable" : "must not be rankable",
    requires_all_columns: v => `has columns ${listOf(v)}`,
    requires_any_columns: v => `has a column ${listOf(v)}`,
    required_settings: v => `setting: ${listOf(v)}`,
    required_packages: v => `package: ${listOf(v)}`,
  };

  function requirementHtml(requirement) {
    const keys = Object.keys(requirement || {});
    if (!keys.length) return '<p class="pc-muted">Runs on almost any dataset.</p>';
    const chips = keys.map(key => {
      const fmt = REQ_LABEL[key];
      const text = fmt ? fmt(requirement[key]) : `${key.replace(/_/g, " ")}: ${listOf(requirement[key])}`;
      return `<span class="pc-chip pc-req">${esc(text)}</span>`;
    }).join("");
    return `<div class="pc-chips">${chips}</div>`;
  }

  // clickable data-source chips, capped with a "+N more" reveal when the group is large
  function sourceChips(sources) {
    const CAP = 12;
    const chip = t => `<button class="pc-chip pc-src" data-type="${esc(t)}">${esc(titleOf(t))}</button>`;
    if (sources.length <= CAP) return `<div class="pc-chips">${sources.map(chip).join("")}</div>`;
    const shown = sources.slice(0, CAP).map(chip).join("");
    const rest = sources.slice(CAP).map(chip).join("");
    return `<div class="pc-chips">${shown}<span class="pc-more-wrap" hidden>${rest}</span>`
      + `<button class="pc-more" type="button">+${sources.length - CAP} more</button></div>`;
  }

  // "Where to start": the data sources, grouped by the route to reach this processor.
  // Sources you can run it on directly come first; the rest are grouped by the one step
  // you run first (so a route shared by many sources is shown once, not once per source).
  function dataSourcesHtml(points, currentTitle) {
    if (!points || !points.length) return "";
    const groups = new Map();  // route key -> {then: [step], sources: [type]}
    points.forEach(sp => {
      const then = sp.then || [];
      const key = then.map(step => step.type).join(">") || "__direct__";
      if (!groups.has(key)) groups.set(key, { then, sources: [] });
      groups.get(key).sources.push(sp.datasource);
    });
    const entries = [...groups.entries()].sort((a, b) =>
      a[0] === "__direct__" ? -1 : b[0] === "__direct__" ? 1 : a[0].localeCompare(b[0]));

    const rows = entries.map(([key, group]) => {
      const label = key === "__direct__"
        ? `<span class="pc-route-direct">Run directly → ${esc(currentTitle)}</span>`
        : "via " + group.then.map(step =>
            `<span class="pc-route-step" data-type="${esc(step.type)}">${esc(step.title)}</span>`).join(" → ")
          + ` → ${esc(currentTitle)}`;
      const sources = group.sources.slice().sort((a, b) => titleOf(a).localeCompare(titleOf(b)));
      return `<div class="pc-route"><p class="pc-route-label">${label}</p>${sourceChips(sources)}</div>`;
    }).join("");
    return '<p class="pc-sub">Data sources — where to start</p>' + rows;
  }

  function section(title, open, inner) {
    return `<details class="pc-section"${open ? " open" : ""}><summary>${esc(title)}</summary><div class="pc-section-body">${inner}</div></details>`;
  }

  // a collapsible sub-heading (styled like a pc-sub label), collapsed by default
  function subCollapse(title, count, inner) {
    const badge = count != null ? ` <span class="pc-muted">(${count})</span>` : "";
    return `<details class="pc-collapse"><summary class="pc-sub">${esc(title)}${badge}</summary>${inner}</details>`;
  }

  function howToRunHtml(info) {
    const htr = info.how_to_run || {};

    if (htr.is_filter || info.is_filter)
      return (htr.notes || ["This is a filter: it runs on almost any dataset and keeps its format."])
        .map(note => `<p>${esc(note)}</p>`).join("");

    if (info.is_datasource)
      return (htr.notes || ["This is a data source: run it to start collecting data."])
        .map(note => `<p>${esc(note)}</p>`).join("");

    const accepts = htr.accepts || {};
    // data sources first -- the main takeaway: where can I start to reach this?
    let how = dataSourcesHtml(htr.starting_points, info.title || info.type);
    how += '<p class="pc-sub">Needs a dataset that…</p>' + requirementHtml(accepts.requirement);
    if ((accepts.from_processors || []).length)
      how += subCollapse("Runs on the output of", accepts.from_processors.length,
                         chipRow(accepts.from_processors, ""));
    (htr.notes || []).forEach(note => { how += `<p class="pc-cond">${esc(note)}</p>`; });
    return how;
  }

  function followupsHtml(info) {
    const fu = info.followups || {};
    let next = "";
    if ((fu.preferred || []).length)
      next += '<p class="pc-sub">Suggested next</p>' + chipRow(fu.preferred, "pc-next");
    if ((fu.filters || []).length)
      next += '<p class="pc-sub">Filters — narrow the data, keep the format</p>' + chipRow(fu.filters, "pc-next");
    const others = fu.others_by_category || {};
    Object.keys(others).sort().forEach(category => {
      next += `<p class="pc-sub">${esc(category)}</p>` + chipRow(others[category], "pc-next");
    });
    if (fu.note) next += `<p class="pc-cond">${esc(fu.note)}</p>`;
    return next || '<p class="pc-muted">Nothing runs on this output.</p>';
  }

  function detailHtml(info) {
    const shape = info.output_shape || {};

    const badges = [
      info.is_datasource ? '<span class="inline-label property-badge pc-source">data source</span>' : "",
      info.is_filter ? '<span class="inline-label property-badge pc-filter">filter</span>' : "",
      info.has_override ? '<span class="inline-label property-badge pc-approx">override — approximate</span>' : "",
      info.requires_dataset_result_file ? '<span class="inline-label property-badge pc-maybe">needs dataset data</span>' : ""
    ].join("");

    const spec = info.compatibility
      ? `<pre class="pc-spec">${esc(JSON.stringify(info.compatibility, null, 2))}</pre>`
      : '<p class="pc-muted">No declared compatibility (defaults to top-level datasets).</p>';
    const produces = [shape.extension, shape.media_type].filter(v => v && v !== "unknown").join(" · ");

    return `
      <h2><span>${esc(info.title || info.type)}</span></h2>
      <p class="pc-badges">${badges}</p>
      <dl class="metadata-wrapper">
        <div class="fullwidth"><dt>Type</dt><dd><code>${esc(info.type)}</code></dd></div>
        ${info.category ? `<div class="fullwidth"><dt>Category</dt><dd>${esc(info.category)}</dd></div>` : ""}
        ${produces ? `<div class="fullwidth"><dt>Produces</dt><dd>${esc(produces)}</dd></div>` : ""}
        ${info.description ? `<div class="fullwidth"><dt>About</dt><dd>${esc(info.description)}</dd></div>` : ""}
      </dl>
      ${section("How to run", true, howToRunHtml(info))}
      ${section("What can run on this", true, followupsHtml(info))}
      ${section("Compatibility (declared)", false, spec)}
    `;
  }

  if (document.readyState !== "loading") init();
  else document.addEventListener("DOMContentLoaded", init);
})();
