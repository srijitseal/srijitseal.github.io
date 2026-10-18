(function () {
  "use strict";

  const number = new Intl.NumberFormat("en-US");
  document.querySelectorAll("[data-count]").forEach((element) => {
    const value = element.dataset.count;
    if (/^\d+$/.test(value)) element.textContent = number.format(Number(value));
  });

  const form = document.getElementById("post-filters");
  const tbody = document.getElementById("post-rows");
  if (!form || !tbody) return;
  const rows = Array.from(tbody.rows);
  const search = document.getElementById("post-search");
  const topic = document.getElementById("post-topic");
  const year = document.getElementById("post-year");
  const defaultYear = form.dataset.defaultYear;
  const years = new Set(Array.from(year.options, (option) => option.value));
  const counter = document.getElementById("post-count");
  const more = document.getElementById("show-more");
  const empty = document.getElementById("empty-results");
  const sortButtons = Array.from(document.querySelectorAll("[data-sort]"));
  const pageSize = 10;
  let visibleLimit = pageSize;
  let sortBy = "impressions";
  let direction = "descending";

  function normalize(value) {
    return value.normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  }

  function applyURL() {
    const params = new URLSearchParams(location.search);
    search.value = params.get("q") || "";
    topic.value = params.get("topic") || "";
    year.value = years.has(params.get("year")) ? params.get("year") : defaultYear;
    if (!topic.value) topic.value = "";
    sortBy = ["impressions", "reactions", "date"].includes(params.get("sort")) ? params.get("sort") : "impressions";
    direction = params.get("direction") === "ascending" ? "ascending" : "descending";
    visibleLimit = pageSize;
  }

  function updateURL() {
    const url = new URL(location.href);
    const values = { q: search.value.trim(), topic: topic.value, year: year.value,
      sort: sortBy === "impressions" ? "" : sortBy,
      direction: direction === "descending" ? "" : direction };
    Object.entries(values).forEach(([key, value]) => {
      if (value) url.searchParams.set(key, value);
      else url.searchParams.delete(key);
    });
    history.replaceState(null, "", url);
  }

  function compare(a, b) {
    const left = a.dataset[sortBy];
    const right = b.dataset[sortBy];
    // Missing export counts remain unknown and sort last in either direction.
    if (!left && right) return 1;
    if (left && !right) return -1;
    const diff = sortBy === "date" ? left.localeCompare(right) : Number(left) - Number(right);
    return (direction === "descending" ? -diff : diff) || b.dataset.date.localeCompare(a.dataset.date);
  }

  function render(syncURL = true) {
    rows.forEach((row) => {
      const metrics = JSON.parse(row.dataset.metrics);
      const combined = year.value === "all";
      const value = combined ? (row.dataset.combinedImpressions === "" ? null : Number(row.dataset.combinedImpressions)) : metrics[year.value]?.impressions;
      const partial = combined && row.dataset.combinedPartial === "true";
      const period = combined ? JSON.parse(row.dataset.combinedPeriod) : metrics[year.value]?.period;
      row.dataset.impressions = value == null ? "" : String(value);
      const cell = row.querySelector(".impression-value");
      cell.textContent = value == null ? "N/A" : number.format(value) + (partial ? "+" : "");
      cell.title = value == null ? "No verified count for this period" :
        `${partial ? "At least " : ""}${number.format(value)} impressions in available exports from ${period.start} to ${period.end}`;
    });
    const terms = normalize(search.value.trim()).split(/\s+/).filter(Boolean);
    const filtered = rows.filter((row) => {
      const text = normalize(row.querySelector(".post-description").textContent);
      return terms.every((term) => text.includes(term)) &&
        (!topic.value || row.dataset.topic === topic.value) &&
        (year.value === "all" || row.dataset.date.startsWith(year.value + "-"));
    }).sort(compare);
    rows.forEach((row) => { row.hidden = true; });
    filtered.forEach((row, index) => {
      row.hidden = index >= visibleLimit;
      tbody.appendChild(row);
    });
    const shown = Math.min(visibleLimit, filtered.length);
    counter.textContent = `${shown} of ${filtered.length} posts`;
    more.hidden = shown >= filtered.length;
    empty.hidden = filtered.length > 0;
    document.querySelectorAll(".year-snapshot").forEach((panel) => {
      panel.hidden = panel.dataset.year !== year.value;
    });
    sortButtons.forEach((button) => {
      const active = button.dataset.sort === sortBy;
      button.closest("th").setAttribute("aria-sort", active ? direction : "none");
      button.querySelector("i").className = `fas ${active ? (direction === "ascending" ? "fa-sort-up" : "fa-sort-down") : "fa-sort"}`;
    });
    if (syncURL) updateURL();
  }

  form.hidden = false;
  form.addEventListener("submit", (event) => event.preventDefault());
  search.addEventListener("input", () => { visibleLimit = pageSize; render(); });
  [topic, year].forEach((select) => select.addEventListener("change", () => {
    visibleLimit = pageSize;
    render();
  }));
  sortButtons.forEach((button) => {
    button.disabled = false;
    button.addEventListener("click", () => {
      direction = sortBy === button.dataset.sort && direction === "descending" ? "ascending" : "descending";
      sortBy = button.dataset.sort;
      visibleLimit = pageSize;
      render();
    });
  });
  more.addEventListener("click", () => {
    const nextIndex = visibleLimit;
    visibleLimit += pageSize;
    render();
    const visibleRows = Array.from(tbody.rows).filter((row) => !row.hidden);
    visibleRows[nextIndex]?.querySelector("a")?.focus({ preventScroll: true });
  });
  document.getElementById("reset-filters").addEventListener("click", () => {
    search.value = "";
    topic.value = "";
    visibleLimit = pageSize;
    render();
    search.focus();
  });
  window.addEventListener("popstate", () => { applyURL(); render(false); });
  applyURL();
  render(false);

  document.querySelectorAll(".chart-column").forEach((column) => {
    const readout = column.closest(".chart-section").querySelector(".chart-readout");
    const showMonth = () => {
      readout.querySelector("span").textContent = column.dataset.month + (column.dataset.partial === "true" ? " (partial)" : "");
      readout.querySelector("strong").textContent = number.format(Number(column.dataset.value));
    };
    column.addEventListener("mouseenter", showMonth);
    column.addEventListener("focus", showMonth);
    column.addEventListener("click", showMonth);
  });
})();
