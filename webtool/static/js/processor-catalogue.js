/* Processor catalogue (prototype).
 *
 * A thin reactive client over the /api/processor-map/* endpoints: browse/search
 * processors, then open one to see "how to run this" (the dataset it needs and the
 * sensible ways to get there from a data source) and "what can run on this" (the
 * follow-up processors and filters its output unlocks). Holds no compatibility
 * logic itself -- that all lives in common/lib/processor_map.py; this file only
 * fetches what that computed and lays it out.
 */
(function () {
  "use strict";

  const API = "/api/processor-map";
  let CATALOGUE = [];   // every processor, as returned by the catalogue endpoint
  const TITLE = {};     // processor type -> display title, so links can show names not ids

  // small text helpers: escape for HTML, look up a title by type, join a value for display
  const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g,
    c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const titleOf = t => TITLE[t] || t;
  const listOf = v => Array.isArray(v) ? v.join(", ") : String(v);

  // Fetch one of the map's JSON endpoints. Throws on an HTTP error so the caller can
  // show a message rather than rendering half a page.
  async function getJSON(url) {
    const response = await fetch(url);
    if (!response.ok) throw new Error("HTTP " + response.status);
    return response.json();
  }

  // On load: pull the whole catalogue once, remember every title, wire up the search
  // box and category dropdown, and draw the list. Everything after this is redrawing.
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

  // Fill the category dropdown with the categories actually present in the catalogue.
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

  // Draw the browse list: keep the processors matching the search box and the selected
  // category, group them by category, and render a card for each. Also updates the
  // "N of M" count and re-attaches the click handler that opens a card's detail.
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

  // One processor as a clickable browse card: title, a badge or two (data source /
  // filter / keeps a custom compatibility override), and its description.
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

  // Load one processor's full detail from the API and render it into the top pane. Then
  // wire the links: every element carrying a data-type opens that processor when clicked.
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
  }

  // A row of clickable chips, one per processor. A link the map is only unsure about
  // ("maybe") is marked with a "?" -- the specs can't promise it applies, only that it
  // might, so it is shown but flagged rather than hidden.
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

  // Turns each condition a processor declares (the keys of the map's "requirement")
  // into a short plain phrase. A key not listed here falls back to a generic "key: value".
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

  // The dataset conditions a processor needs, as plain non-clickable chips; says
  // "almost any dataset" when it declares none.
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

  // A few concrete example paths, each drawn as a chain: data source → steps → this. The
  // API returns the shortest few (one per distinct recipe), so these read as "here are a
  // couple of ways it's done", not an exhaustive list. Empty means nothing reaches this by
  // confirmed steps -- flagged, as that usually points at a spec gap.
  function examplesHtml(examples, currentTitle) {
    const heading = '<p class="pc-sub">Example ways to reach this</p>';
    if (!examples || !examples.length)
      return heading + '<p class="pc-cond">No data source reaches this by confirmed steps — likely an '
        + 'over-strict requirement or a missing link between processors.</p>';

    const chains = examples.map(example => {
      const parts = [`<span class="pc-step pc-src" data-type="${esc(example.datasource)}">${esc(example.title)}</span>`];
      (example.then || []).forEach(step => {
        parts.push('<span class="pc-arrow">→</span>');
        parts.push(`<span class="pc-step" data-type="${esc(step.type)}">${esc(step.title)}</span>`);
      });
      parts.push('<span class="pc-arrow">→</span>');
      parts.push(`<span class="pc-step pc-current">${esc(currentTitle)}</span>`);
      return `<div class="pc-chain">${parts.join("")}</div>`;
    }).join("");

    const note = '<p class="pc-cond">A few of the shortest ways in — examples, not the only routes. '
      + 'Most processors can be reached other ways too; click any step to explore from there.</p>';
    return heading + chains + note;
  }

  // A large collapsible block in the detail pane (How to run / What can run on this /
  // Compatibility). `open` decides whether it starts expanded.
  function section(title, open, inner) {
    return `<details class="pc-section"${open ? " open" : ""}><summary>${esc(title)}</summary><div class="pc-section-body">${inner}</div></details>`;
  }

  // A smaller collapsible sub-heading inside a block, with a count, collapsed by default
  // -- for a secondary list that would otherwise crowd out the main point.
  function subCollapse(title, count, inner) {
    const badge = count != null ? ` <span class="pc-muted">(${count})</span>` : "";
    return `<details class="pc-collapse"><summary class="pc-sub">${esc(title)}${badge}</summary>${inner}</details>`;
  }

  // The "How to run" block. A filter or a data source doesn't "run on" anything, so each
  // gets a one-line explanation. Any other processor leads with a few example paths to
  // reach it, then the dataset it needs, then -- collapsed -- the processors whose output
  // it takes directly, then any caveats.
  function howToRunHtml(info) {
    const htr = info.how_to_run || {};

    if (htr.is_filter || info.is_filter)
      return (htr.notes || ["This is a filter: it runs on almost any dataset and keeps its format."])
        .map(note => `<p>${esc(note)}</p>`).join("");

    if (info.is_datasource)
      return (htr.notes || ["This is a data source: run it to start collecting data."])
        .map(note => `<p>${esc(note)}</p>`).join("");

    const accepts = htr.accepts || {};
    let how = examplesHtml(htr.examples, info.title || info.type);
    how += '<p class="pc-sub">Needs a dataset that…</p>' + requirementHtml(accepts.requirement);
    if ((accepts.from_processors || []).length)
      how += subCollapse("Runs on the output of", accepts.from_processors.length,
                         chipRow(accepts.from_processors, ""));
    (htr.notes || []).forEach(note => { how += `<p class="pc-cond">${esc(note)}</p>`; });
    return how;
  }

  // The "What can run on this" block: the curated "suggested next" first, then filters
  // (kept apart -- they narrow the data without changing its format), then everything
  // else grouped by category. A closing note appears for filters (see the API).
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

  // Assemble the whole detail pane for one processor: heading and badges, a short
  // metadata list (type / category / what it produces / description), then the three
  // blocks. "Produces" is left out when the output shape didn't pin down a format.
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
