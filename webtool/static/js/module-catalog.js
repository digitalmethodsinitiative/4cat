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
  let BROWSE_PLACEHOLDER = "";  // detail pane's empty state, kept so back/forward can restore it

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
  // When the page is a deep link, the selected processor is fetched and drawn first --
  // its request goes out alongside the catalogue's, and its detail paints before the grid.
  async function init() {
    const initial = (document.getElementById("pc-page").dataset.initialProcessor || "").trim();

    // On a deep link, start the selected processor's request right away -- in parallel with
    // the larger catalogue request rather than queued behind it -- so its content is ready
    // as soon as possible. Pre-caught to null so a bad type raises no unhandled rejection;
    // showDetail then treats null as "not found".
    const detailPromise = initial
      ? getJSON(`${API}/processor/${encodeURIComponent(initial)}`).catch(() => null)
      : null;

    let data;
    try {
      data = await getJSON(`${API}/catalogue`);
    } catch (e) {
      document.getElementById("pc-loading").textContent = "Could not load processors.";
      return;
    }
    CATALOGUE = (data.processors || []).slice().sort((a, b) => (a.title || a.type).localeCompare(b.title || b.type));
    CATALOGUE.forEach(p => { TITLE[p.type] = p.title || p.type; });

    populateTags();
    document.getElementById("pc-search").addEventListener("input", renderCatalogue);
    document.getElementById("pc-tag").addEventListener("change", renderCatalogue);

    // Remember the empty-state markup (before anything overwrites it) so back/forward can
    // restore it when the visitor navigates back past every processor they opened.
    BROWSE_PLACEHOLDER = document.getElementById("pc-detail-body").innerHTML;

    // Keep the view in step with the address bar on back/forward. Each opened processor
    // pushed a history entry carrying its type; an entry with no type is the bare
    // catalogue, so restore the empty state.
    window.addEventListener("popstate", event => {
      const type = event.state && event.state.pcType;
      if (type) showDetail(type, "none");
      else document.getElementById("pc-detail-body").innerHTML = BROWSE_PLACEHOLDER;
    });

    // If the page was opened as a deep link (/processor-catalogue/<type>), draw that
    // processor before the browse grid -- but only if it really exists, so a stale or
    // mistyped link just falls through to the browse view. Its request is already in
    // flight (detailPromise) and TITLE is now ready for its follow-up chips. "replace"
    // attaches the type to the current history entry rather than adding a duplicate.
    if (initial && TITLE[initial]) await showDetail(initial, "replace", detailPromise);

    renderCatalogue();
  }

  // Fill the tag dropdown with every tag present in the catalogue. Tags are the new way
  // to filter (a superset of categories -- a processor's first tag is its category), so
  // this lists them all, alphabetically.
  function populateTags() {
    const tags = [...new Set(CATALOGUE.flatMap(p => p.tags || []))].sort();
    const select = document.getElementById("pc-tag");
    tags.forEach(tag => {
      const option = document.createElement("option");
      option.value = tag;
      option.textContent = tag;
      select.appendChild(option);
    });
  }

  // --- catalogue (browse / search) ---

  // Draw the browse list: keep the processors matching the search box and the selected
  // category, group them by category, and render a card for each. Also updates the
  // "N of M" count and re-attaches the click handler that opens a card's detail.
  function renderCatalogue() {
    const query = document.getElementById("pc-search").value.trim().toLowerCase();
    const tag = document.getElementById("pc-tag").value;

    let items = CATALOGUE;
    if (tag) items = items.filter(p => (p.tags || []).includes(tag));
    if (query) items = items.filter(p =>
      `${p.type} ${p.title || ""} ${(p.tags || []).join(" ")} ${p.description || ""}`.toLowerCase().includes(query));

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
    // the first tag is the category (already the group heading), so show only the rest
    const tags = (p.tags || []).slice(1).map(t => `<span class="pc-tag">${esc(t)}</span>`).join("");
    return `<button class="pc-card" data-type="${esc(p.type)}">
      <div class="pc-card-head"><h4>${esc(p.title || p.type)}</h4><span class="pc-badges">${badges}</span></div>
      <p class="pc-desc">${esc(p.description || "")}</p>
      ${tags ? `<div class="pc-tags">${tags}</div>` : ""}
    </button>`;
  }

  // --- detail ("how to run this" / "what can run on this") ---

  // Load one processor's full detail from the API and render it into the top pane. Then
  // wire the links: every element carrying a data-type opens that processor when clicked.
  // `urlMode` says how to reflect this in the address bar (see the note by the history call).
  // `infoPromise`, when given, is an already-in-flight request for this processor (used on
  // first load to avoid firing a second, duplicate request).
  async function showDetail(type, urlMode = "push", infoPromise = null) {
    const body = document.getElementById("pc-detail-body");
    body.innerHTML = '<p class="banner">Loading…</p>';
    window.scrollTo({ top: 0, behavior: "smooth" });
    let info;
    try {
      info = await (infoPromise || getJSON(`${API}/processor/${encodeURIComponent(type)}`));
    } catch (e) {
      body.innerHTML = '<p class="banner">Could not load this processor.</p>';
      return;
    }
    if (!info || !info.type) {
      body.innerHTML = '<p class="banner">Processor not found.</p>';
      return;
    }
    body.innerHTML = detailHtml(info);
    // Reflect the open processor in the address bar so the visitor can copy the URL to
    // share exactly what they are looking at. "push" adds a history entry (a normal
    // click); "replace" rewrites the current one (first load, where the URL is already
    // right); "none" leaves it alone (a back/forward already moved the URL for us).
    const url = `/processor-catalogue/${encodeURIComponent(type)}`;
    if (urlMode === "push") history.pushState({ pcType: type }, "", url);
    else if (urlMode === "replace") history.replaceState({ pcType: type }, "", url);
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

  // Render a references-style string: turn any [text](url) markdown links into anchors,
  // escaping everything else. Plain citations (no link) pass through unchanged.
  function mdLinks(s) {
    let out = "", last = 0, re = /\[([^\]]+)\]\(([^)]+)\)/g, m;
    while ((m = re.exec(s))) {
      out += esc(s.slice(last, m.index));
      out += `<a href="${esc(m[2])}" target="_blank" rel="noopener">${esc(m[1])}</a>`;
      last = m.index + m[0].length;
    }
    return out + esc(s.slice(last));
  }

  // Info / warning notice boxes, styled like the run-processor card: warnings (pitfalls)
  // in yellow, info (helpful extras) in blue. One box per item, matching the design mockup.
  function noticeBoxes(items, kind) {
    if (!items || !items.length) return "";
    const icon = kind === "warning" ? "triangle-exclamation" : "circle-info";
    return items.map(t =>
      `<p class="pc-notice pc-notice-${kind}"><i class="fa fa-${icon}" aria-hidden="true"></i><span>${esc(t)}</span></p>`
    ).join("");
  }

  // Assemble the whole detail pane for one processor: a card (icon + title + badges/tags,
  // description, warning then info boxes, and a footer of what it produces + references),
  // then a compact type/category line and the three collapsible blocks.
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

    // the first tag is the category (shown below), so chip only the rest next to the title
    const tags = (info.tags || []).slice(1).map(t => `<span class="pc-tag">${esc(t)}</span>`).join("");
    const icon = info.icon ? `<i class="fa fa-fw fa-${esc(info.icon)}" aria-hidden="true"></i> ` : "";
    const references = (info.references || []).length
      ? `<div class="pc-refs">${info.references.map(r => `<span>${mdLinks(r)}</span>`).join("")}</div>` : "";
    const foot = (produces || references)
      ? `<div class="pc-detail-foot">${produces ? `<span class="pc-produces"><i class="fa fa-table" aria-hidden="true"></i> ${esc(produces)}</span>` : "<span></span>"}${references}</div>`
      : "";

    return `
      <div class="pc-detail-card">
        <header class="pc-detail-head">
          <h2>${icon}<span>${esc(info.title || info.type)}</span></h2>
          <span class="pc-badges">${badges}${tags}</span>
        </header>
        ${info.description ? `<p class="pc-detail-desc">${esc(info.description)}</p>` : ""}
        ${noticeBoxes(info.warnings, "warning")}
        ${noticeBoxes(info.info, "info")}
        ${foot}
      </div>
      <dl class="metadata-wrapper pc-meta">
        <div class="fullwidth"><dt>Type</dt><dd><code>${esc(info.type)}</code></dd></div>
        ${info.category ? `<div class="fullwidth"><dt>Category</dt><dd>${esc(info.category)}</dd></div>` : ""}
      </dl>
      ${section("How to run", true, howToRunHtml(info))}
      ${section("What can run on this", false, followupsHtml(info))}
      ${section("Compatibility (declared)", false, spec)}
    `;
  }

  if (document.readyState !== "loading") init();
  else document.addEventListener("DOMContentLoaded", init);
})();
