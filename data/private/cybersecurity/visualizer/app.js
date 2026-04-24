const API_VIEW = "/api/view";
const API_MANIFEST = "/api/manifest";
const API_EXPORT = "/api/export";
const ANY_VALUE = "__RUNBOOK_ANY__";

const numberFormatter = new Intl.NumberFormat("en-US");

const state = {
  manifest: null,
  view: null,
  filters: {},
};

const elements = {
  status: document.getElementById("status"),
  sourceFormat: document.getElementById("source-format"),
  shardCount: document.getElementById("shard-count"),
  totalRows: document.getElementById("total-rows"),
  matchingRows: document.getElementById("matching-rows"),
  outputDir: document.getElementById("output-dir"),
  wizardColumns: document.getElementById("wizard-columns"),
  resultsHead: document.getElementById("results-head"),
  resultsBody: document.getElementById("results-body"),
  previewNote: document.getElementById("preview-note"),
  clearButton: document.getElementById("clear-button"),
  refreshButton: document.getElementById("refresh-button"),
  exportRowsButton: document.getElementById("export-rows-button"),
};

document.addEventListener("DOMContentLoaded", () => {
  bindEvents();
  void loadAll();
});

function bindEvents() {
  elements.clearButton.addEventListener("click", () => {
    state.filters = {};
    void loadView();
  });

  elements.refreshButton.addEventListener("click", () => {
    void loadAll();
  });

  elements.exportRowsButton.addEventListener("click", () => {
    void exportRows();
  });
}

async function loadAll() {
  setStatus("Loading runbook shard metadata...");
  try {
    state.manifest = await fetchJson(API_MANIFEST);
    await loadView();
  } catch (error) {
    setStatus(`Could not load visualizer data: ${error.message}`);
  }
}

async function loadView() {
  const url = `${API_VIEW}?filters=${encodeURIComponent(JSON.stringify(state.filters))}`;
  setStatus("Updating flow columns...");
  try {
    state.view = await fetchJson(url);
    state.filters = { ...state.view.filters };
    render();
    setStatus("Ready.");
  } catch (error) {
    setStatus(`Could not update view: ${error.message}`);
  }
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || response.statusText);
  }
  return payload;
}

function render() {
  renderMetrics();
  renderWizard();
  renderResults();
}

function renderMetrics() {
  const view = state.view || {};
  const manifest = state.manifest || {};
  elements.sourceFormat.textContent = uppercase(view.source_format || manifest.source_format || "-");
  elements.shardCount.textContent = numberFormatter.format((view.shards || manifest.shards || []).length);
  elements.totalRows.textContent = numberFormatter.format(view.total_rows || manifest.total_rows || 0);
  elements.matchingRows.textContent = numberFormatter.format(view.matching_count || 0);
  elements.outputDir.textContent = manifest.output_dir || "-";
}

function renderWizard() {
  const view = state.view;
  elements.wizardColumns.textContent = "";

  if (!view || !Array.isArray(view.columns) || !view.columns.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No runbook columns were found in the available shards.";
    elements.wizardColumns.appendChild(empty);
    return;
  }

  view.columns.forEach((column, index) => {
    elements.wizardColumns.appendChild(renderColumn(column, index));
  });
}

function renderColumn(column, index) {
  const field = column.field;
  const hasSelectedValue = Object.prototype.hasOwnProperty.call(state.filters, field);
  const selectedValue = hasSelectedValue ? state.filters[field] : ANY_VALUE;
  const wrapper = document.createElement("article");
  wrapper.className = "flow-column";

  const header = document.createElement("div");
  header.className = "column-header";
  const title = document.createElement("h3");
  title.textContent = labelFor(field);
  const detail = document.createElement("p");
  detail.textContent = `${numberFormatter.format(column.total_options || 0)} values from ${numberFormatter.format(
    column.matched_rows || 0,
  )} rows`;
  header.append(title, detail);

  const selectWrap = document.createElement("div");
  selectWrap.className = "column-select";
  const label = document.createElement("label");
  label.className = "field-label";
  label.textContent = "Filter";
  const select = document.createElement("select");
  select.setAttribute("aria-label", `Filter ${labelFor(field)}`);
  select.appendChild(new Option("Any value", ANY_VALUE));
  (column.options || []).forEach((option) => {
    const labelText = `${displayValue(option.value)} (${numberFormatter.format(option.count)})`;
    select.appendChild(new Option(labelText, option.value));
  });
  select.value = selectedValue;
  select.addEventListener("change", () => {
    setFilter(field, select.value, index);
  });
  label.appendChild(select);
  selectWrap.appendChild(label);

  const list = document.createElement("div");
  list.className = "option-list";
  if (!column.options || !column.options.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No values match the current path.";
    list.appendChild(empty);
  } else {
    column.options.slice(0, 80).forEach((option) => {
      const button = document.createElement("button");
      button.type = "button";
      const isActive = hasSelectedValue && option.value === selectedValue;
      button.className = isActive ? "option-button is-active" : "option-button";
      button.title = displayValue(option.value);
      button.addEventListener("click", () => {
        setFilter(field, option.value, index);
      });

      const value = document.createElement("span");
      value.className = option.value ? "option-value" : "option-value blank";
      value.textContent = displayValue(option.value);

      const count = document.createElement("span");
      count.className = "option-count";
      count.textContent = numberFormatter.format(option.count);

      button.append(value, count);
      list.appendChild(button);
    });
  }

  const footer = document.createElement("div");
  footer.className = "column-footer";
  const exportButton = document.createElement("button");
  exportButton.type = "button";
  exportButton.className = "button small";
  exportButton.textContent = "Export column CSV";
  exportButton.addEventListener("click", () => {
    void exportColumn(field);
  });
  footer.appendChild(exportButton);

  if (column.truncated) {
    const warning = document.createElement("p");
    warning.className = "column-warning";
    warning.textContent = `Showing first ${numberFormatter.format(column.options.length)} of ${numberFormatter.format(
      column.total_options,
    )} values. Export includes all values.`;
    footer.appendChild(warning);
  } else if (column.options && column.options.length > 80) {
    const warning = document.createElement("p");
    warning.className = "column-warning";
    warning.textContent = `List preview shows 80 values. Use the dropdown for the full column.`;
    footer.appendChild(warning);
  }

  wrapper.append(header, selectWrap, list, footer);
  return wrapper;
}

function renderResults() {
  const view = state.view;
  elements.resultsHead.textContent = "";
  elements.resultsBody.textContent = "";

  if (!view || !Array.isArray(view.headers) || !view.headers.length) {
    elements.previewNote.textContent = "";
    return;
  }

  const headerRow = document.createElement("tr");
  view.headers.forEach((header) => {
    const th = document.createElement("th");
    th.textContent = labelFor(header);
    headerRow.appendChild(th);
  });
  elements.resultsHead.appendChild(headerRow);

  (view.rows || []).forEach((row) => {
    const tr = document.createElement("tr");
    view.headers.forEach((header) => {
      const td = document.createElement("td");
      const value = row[header] || "";
      td.textContent = displayValue(value);
      if (!value) {
        td.className = "blank";
      }
      tr.appendChild(td);
    });
    elements.resultsBody.appendChild(tr);
  });

  if (!view.rows || !view.rows.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.className = "empty-state";
    td.colSpan = view.headers.length;
    td.textContent = "No rows match the current path.";
    tr.appendChild(td);
    elements.resultsBody.appendChild(tr);
  }

  const visible = (view.rows || []).length;
  const total = view.matching_count || 0;
  if (total > visible) {
    elements.previewNote.textContent = `Showing ${numberFormatter.format(visible)} of ${numberFormatter.format(
      total,
    )} matching rows. Export writes all matches.`;
  } else {
    elements.previewNote.textContent = `${numberFormatter.format(total)} matching rows.`;
  }
}

function setFilter(field, value, index) {
  const nextFilters = {};
  const hierarchy = (state.view && state.view.hierarchy) || [];

  hierarchy.forEach((currentField, currentIndex) => {
    if (currentIndex < index && Object.prototype.hasOwnProperty.call(state.filters, currentField)) {
      nextFilters[currentField] = state.filters[currentField];
    }
  });

  if (value !== ANY_VALUE) {
    nextFilters[field] = value;
  }

  state.filters = nextFilters;
  void loadView();
}

async function exportColumn(field) {
  setStatus(`Writing ${labelFor(field)} column CSV...`);
  try {
    const payload = await fetchJson(API_EXPORT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ field, filters: state.filters }),
    });
    setStatus(`Wrote ${numberFormatter.format(payload.rows_written)} rows to ${payload.path}.`);
  } catch (error) {
    setStatus(`Export failed: ${error.message}`);
  }
}

async function exportRows() {
  setStatus("Writing matching row CSV...");
  try {
    const payload = await fetchJson(API_EXPORT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type: "rows", filters: state.filters }),
    });
    setStatus(`Wrote ${numberFormatter.format(payload.rows_written)} rows to ${payload.path}.`);
  } catch (error) {
    setStatus(`Export failed: ${error.message}`);
  }
}

function setStatus(message) {
  elements.status.textContent = message;
}

function displayValue(value) {
  return value === "" ? "(blank)" : String(value);
}

function labelFor(field) {
  return String(field || "")
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function uppercase(value) {
  return String(value || "").toUpperCase();
}
