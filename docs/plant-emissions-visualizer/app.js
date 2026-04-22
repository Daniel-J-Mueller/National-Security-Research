const MANIFEST_URL = "../../data/private/visualizer/visualizer_manifest.json";
const HEAT_PANE = "heatPane";
const POINT_PANE = "pointPane";

const SPECIAL_GROUP_COLORS = {
  NG: "#5f8d4e",
  SUN: "#d4a43c",
  NUC: "#5a5cbd",
  WND: "#3a7ca5",
  WAT: "#2f6b8f",
  DFO: "#7c5c47",
  BIT: "#3b3531",
  SUB: "#56423d",
  WDL: "#7f5539",
};

const HEADER_LABEL_OVERRIDES = {
  geoid: "GEOID",
  frs_id: "FRS ID",
  ghgrp_frs_id: "GHGRP FRS ID",
  ghgrp_facility_id: "GHGRP Facility ID",
  primary_naics_code: "Primary NAICS Code",
  ghgrp_primary_naics_code: "GHGRP Primary NAICS Code",
  co2e_emissions_value: "CO2e Emissions Value",
  total_reported_direct_emissions_mtco2e: "Total Reported Direct Emissions (MTCO2e)",
  iron_and_steel_production_emissions_mtco2e: "Iron and Steel Production Emissions (MTCO2e)",
  latitude: "Latitude",
  longitude: "Longitude",
};

const state = {
  manifest: [],
  datasetCache: new Map(),
  dataset: null,
  records: [],
  filteredRecords: [],
  activeCategoryKey: "",
  activeMetricKey: "",
  activeRecordId: "",
  hoverRecordId: "",
  map: null,
  pointLayer: null,
  heatLayer: null,
  canvasRenderer: null,
};

const numberFormatter = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });
const integerFormatter = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

const elements = {
  categorySelect: document.getElementById("category-select"),
  metricSelect: document.getElementById("metric-select"),
  viewSelect: document.getElementById("view-select"),
  stateSelect: document.getElementById("state-select"),
  groupSelect: document.getElementById("group-select"),
  groupLabel: document.getElementById("group-filter-label"),
  searchLabel: document.getElementById("search-label"),
  searchInput: document.getElementById("search-input"),
  minimumInput: document.getElementById("minimum-input"),
  zoomFiltered: document.getElementById("zoom-filtered"),
  resetFilters: document.getElementById("reset-filters"),
  visibleCount: document.getElementById("visible-count"),
  metricTotal: document.getElementById("metric-total"),
  metricMax: document.getElementById("metric-max"),
  metricName: document.getElementById("metric-name"),
  resultsHeading: document.getElementById("results-heading"),
  resultsList: document.getElementById("results-list"),
  detailHeading: document.getElementById("detail-heading"),
  detailPanel: document.getElementById("detail-panel"),
  datasetDescription: document.getElementById("dataset-description"),
  statusPill: document.getElementById("status-pill"),
};

document.addEventListener("DOMContentLoaded", () => {
  void init();
});

async function init() {
  bindEvents();
  buildMap();
  setStatus("Loading visualizer manifest...");

  try {
    const payload = await fetchJson(MANIFEST_URL);
    if (!payload || !Array.isArray(payload.datasets) || !payload.datasets.length) {
      throw new Error("visualizer_manifest.json does not contain any datasets.");
    }

    state.manifest = payload.datasets
      .map((dataset) => ({
        key: stringValue(dataset.key),
        label: stringValue(dataset.label),
        path: stringValue(dataset.path),
        description: stringValue(dataset.description),
        defaultMetricKey: stringValue(dataset.default_metric_key),
        groupLabel: stringValue(dataset.group_label),
        recordCount: toNumber(dataset.record_count),
      }))
      .filter((dataset) => dataset.key && dataset.path);

    if (!state.manifest.length) {
      throw new Error("No valid dataset entries were found in visualizer_manifest.json.");
    }

    populateCategoryOptions();
    state.activeCategoryKey = state.manifest[0].key;
    elements.categorySelect.value = state.activeCategoryKey;
    await activateCategory(state.activeCategoryKey, { fitBounds: true });
  } catch (error) {
    console.error(error);
    setStatus(
      "Could not load the visualizer manifest. Serve the repo root over HTTP before opening this page.",
      "error",
    );
  }
}

function bindEvents() {
  elements.categorySelect.addEventListener("change", async () => {
    state.activeCategoryKey = elements.categorySelect.value;
    await activateCategory(state.activeCategoryKey, { fitBounds: true });
  });

  elements.metricSelect.addEventListener("change", () => {
    state.activeMetricKey = elements.metricSelect.value;
    refreshView();
  });

  elements.viewSelect.addEventListener("change", () => {
    refreshView();
  });

  elements.stateSelect.addEventListener("change", () => {
    refreshView();
  });

  elements.groupSelect.addEventListener("change", () => {
    refreshView();
  });

  elements.searchInput.addEventListener("input", () => {
    refreshView();
  });

  elements.minimumInput.addEventListener("input", () => {
    refreshView();
  });

  elements.zoomFiltered.addEventListener("click", () => {
    zoomToFiltered();
  });

  elements.resetFilters.addEventListener("click", () => {
    elements.stateSelect.value = "";
    elements.groupSelect.value = "";
    elements.searchInput.value = "";
    elements.minimumInput.value = "";
    elements.viewSelect.value = "both";
    refreshView({ fitBounds: true });
  });
}

function buildMap() {
  state.map = L.map("map", {
    preferCanvas: true,
    zoomSnap: 0.25,
    minZoom: 2,
  }).setView([39.8, -98.6], 4);

  const heatPane = state.map.createPane(HEAT_PANE);
  heatPane.style.zIndex = "350";
  heatPane.style.pointerEvents = "none";

  const pointPane = state.map.createPane(POINT_PANE);
  pointPane.style.zIndex = "450";

  state.canvasRenderer = L.canvas({
    padding: 0.35,
    pane: POINT_PANE,
  });

  L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
    attribution: "&copy; OpenStreetMap contributors &copy; CARTO",
    subdomains: "abcd",
    maxZoom: 19,
  }).addTo(state.map);

  state.pointLayer = L.layerGroup().addTo(state.map);
}

async function activateCategory(categoryKey, options = {}) {
  if (!categoryKey) {
    return;
  }

  const manifestEntry = state.manifest.find((dataset) => dataset.key === categoryKey);
  if (!manifestEntry) {
    setStatus(`Unknown category: ${categoryKey}`, "error");
    return;
  }

  setStatus(`Loading ${manifestEntry.label}...`);

  try {
    const dataset = await loadDataset(categoryKey);
    state.dataset = dataset;
    state.records = dataset.records;
    state.filteredRecords = dataset.records;
    state.activeCategoryKey = categoryKey;
    state.activeMetricKey = preferredMetricKey(dataset);
    state.activeRecordId = "";
    state.hoverRecordId = "";
    elements.searchInput.value = "";
    elements.minimumInput.value = "";

    updateDatasetChrome();
    populateMetricOptions();
    populateFilters(true);
    refreshView({ fitBounds: options.fitBounds });
  } catch (error) {
    console.error(error);
    setStatus(`Could not load the ${manifestEntry.label} dataset.`, "error");
  }
}

async function loadDataset(categoryKey) {
  if (state.datasetCache.has(categoryKey)) {
    return state.datasetCache.get(categoryKey);
  }

  const manifestEntry = state.manifest.find((dataset) => dataset.key === categoryKey);
  if (!manifestEntry) {
    throw new Error(`Missing dataset entry for ${categoryKey}`);
  }

  const payload = await fetchJson(manifestEntry.path);
  if (!payload || !Array.isArray(payload.records) || !payload.records.length) {
    throw new Error(`${manifestEntry.path} does not contain any mapped records.`);
  }

  const dataset = hydrateDataset(payload, manifestEntry);
  state.datasetCache.set(categoryKey, dataset);
  return dataset;
}

function hydrateDataset(payload, manifestEntry) {
  const headers = Array.isArray(payload.headers)
    ? payload.headers.map((value) => stringValue(value)).filter(Boolean)
    : [];
  const metadata = payload.metadata ?? {};
  const metricDefinitions = Array.isArray(metadata.metrics) ? metadata.metrics : [];

  const records = payload.records
    .map((sourceRecord, index) => {
      const row = sourceRecord?.row && typeof sourceRecord.row === "object" ? sourceRecord.row : {};
      const latitude = toNumber(sourceRecord.latitude ?? row.latitude);
      const longitude = toNumber(sourceRecord.longitude ?? row.longitude);
      if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) {
        return null;
      }

      const metrics = {};
      for (const metric of metricDefinitions) {
        const value = toNumber(sourceRecord.metrics?.[metric.key] ?? row[metric.key]);
        if (Number.isFinite(value)) {
          metrics[metric.key] = value;
        }
      }

      const title = stringValue(sourceRecord.title) || `Record ${index + 1}`;
      const subtitle = stringValue(sourceRecord.subtitle);
      const groupValue = stringValue(sourceRecord.group_value) || "Unspecified";
      const searchText = stringValue(sourceRecord.search_text) || buildSearchText(row);

      return {
        id: stringValue(sourceRecord.id) || `record-${index + 1}`,
        title,
        subtitle,
        state: stringValue(sourceRecord.state || row.state),
        county: stringValue(sourceRecord.county || row.county || row.county_name),
        latitude,
        longitude,
        groupValue,
        metrics,
        searchText: searchText.toLowerCase(),
        row,
      };
    })
    .filter(Boolean);

  const availableMetrics = metricDefinitions.filter((metric) =>
    records.some((record) => Number.isFinite(record.metrics?.[metric.key])),
  );

  if (!availableMetrics.length) {
    throw new Error(`No numeric metrics were found for ${manifestEntry.label}.`);
  }

  return {
    key: manifestEntry.key,
    label: manifestEntry.label,
    headers,
    records,
    metadata: {
      ...metadata,
      metrics: availableMetrics,
      results_label: stringValue(metadata.results_label) || "Results",
      group_label: stringValue(metadata.group_label) || manifestEntry.groupLabel || "Group",
      search_placeholder: stringValue(metadata.search_placeholder) || "Search the active category",
      description: stringValue(metadata.description) || manifestEntry.description || "",
      default_metric_key: stringValue(metadata.default_metric_key) || manifestEntry.defaultMetricKey || availableMetrics[0].key,
    },
  };
}

function populateCategoryOptions() {
  elements.categorySelect.replaceChildren();
  for (const dataset of state.manifest) {
    const option = document.createElement("option");
    option.value = dataset.key;
    option.textContent = dataset.label;
    elements.categorySelect.append(option);
  }
}

function populateMetricOptions() {
  const dataset = state.dataset;
  if (!dataset) {
    return;
  }

  elements.metricSelect.replaceChildren();
  for (const metric of dataset.metadata.metrics) {
    const option = document.createElement("option");
    option.value = metric.key;
    option.textContent = metric.label;
    elements.metricSelect.append(option);
  }
  elements.metricSelect.value = state.activeMetricKey;
}

function populateFilters(resetSelections = false) {
  const dataset = state.dataset;
  if (!dataset) {
    return;
  }

  const previousState = resetSelections ? "" : elements.stateSelect.value;
  const previousGroup = resetSelections ? "" : elements.groupSelect.value;
  const states = [...new Set(dataset.records.map((record) => record.state).filter(Boolean))].sort();
  const groups = [...new Set(dataset.records.map((record) => record.groupValue).filter(Boolean))].sort();

  replaceSelectOptions(elements.stateSelect, states, "All states");
  replaceSelectOptions(elements.groupSelect, groups, `All ${dataset.metadata.group_label.toLowerCase()} groups`);

  if (states.includes(previousState)) {
    elements.stateSelect.value = previousState;
  }
  if (groups.includes(previousGroup)) {
    elements.groupSelect.value = previousGroup;
  }

  elements.groupLabel.textContent = dataset.metadata.group_label;
  elements.searchLabel.textContent = `Search ${dataset.metadata.results_label.toLowerCase()}`;
  elements.searchInput.placeholder = dataset.metadata.search_placeholder;
}

function replaceSelectOptions(select, values, emptyLabel) {
  select.replaceChildren();

  const emptyOption = document.createElement("option");
  emptyOption.value = "";
  emptyOption.textContent = emptyLabel;
  select.append(emptyOption);

  for (const value of values) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.append(option);
  }
}

function updateDatasetChrome() {
  if (!state.dataset) {
    return;
  }

  const countLabel = `${integerFormatter.format(state.dataset.records.length)} ${state.dataset.metadata.results_label.toLowerCase()}`;
  elements.datasetDescription.textContent = `${state.dataset.metadata.description} ${countLabel}.`;
  elements.resultsHeading.textContent = state.dataset.metadata.results_label;
  elements.detailHeading.textContent = `${singularizeLabel(state.dataset.metadata.results_label)} detail`;
  document.title = `${state.dataset.label} Visualizer`;
}

function refreshView(options = {}) {
  if (!state.dataset) {
    return;
  }

  state.filteredRecords = applyFilters();

  if (!state.filteredRecords.some((record) => record.id === state.activeRecordId)) {
    state.activeRecordId = "";
  }
  if (!state.filteredRecords.some((record) => record.id === state.hoverRecordId)) {
    state.hoverRecordId = "";
  }

  const metricStats = buildMetricStats(state.filteredRecords);
  renderSummary(metricStats);
  renderHeatLayer(metricStats);
  renderPointLayer(metricStats);
  renderResults(metricStats);
  renderDetail();

  if (options.fitBounds) {
    zoomToFiltered();
  }
}

function applyFilters() {
  const selectedState = elements.stateSelect.value;
  const selectedGroup = elements.groupSelect.value;
  const searchTerm = elements.searchInput.value.trim().toLowerCase();
  const minimumValue = parseInputNumber(elements.minimumInput.value);

  return state.records.filter((record) => {
    if (selectedState && record.state !== selectedState) {
      return false;
    }
    if (selectedGroup && record.groupValue !== selectedGroup) {
      return false;
    }
    if (searchTerm && !record.searchText.includes(searchTerm)) {
      return false;
    }
    if (minimumValue !== null) {
      const metricValue = getMetricValue(record, state.activeMetricKey);
      if (!Number.isFinite(metricValue) || metricValue < minimumValue) {
        return false;
      }
    }
    return true;
  });
}

function buildMetricStats(records) {
  const values = [];
  let total = 0;
  let maxRecord = null;
  let maxValue = Number.NEGATIVE_INFINITY;
  let positiveCount = 0;

  for (const record of records) {
    const value = getMetricValue(record, state.activeMetricKey);
    if (!Number.isFinite(value)) {
      continue;
    }

    values.push(value);
    total += value;
    if (value > 0) {
      positiveCount += 1;
    }
    if (value > maxValue) {
      maxValue = value;
      maxRecord = record;
    }
  }

  return {
    values,
    countWithMetric: values.length,
    positiveCount,
    total,
    maxValue: Number.isFinite(maxValue) ? maxValue : null,
    maxRecord,
  };
}

function renderSummary(metricStats) {
  elements.visibleCount.textContent = integerFormatter.format(state.filteredRecords.length);
  elements.metricTotal.textContent = metricStats.countWithMetric ? formatMetric(metricStats.total) : "No data";
  elements.metricMax.textContent = metricStats.maxRecord
    ? `${metricStats.maxRecord.title} (${formatMetric(metricStats.maxValue)})`
    : "No data";
  elements.metricName.textContent = metricLabel(state.activeMetricKey);
}

function renderHeatLayer(metricStats) {
  if (state.heatLayer) {
    state.map.removeLayer(state.heatLayer);
    state.heatLayer = null;
  }

  if (elements.viewSelect.value === "points" || typeof L.heatLayer !== "function") {
    return;
  }

  const maxValue = metricStats.maxValue ?? 0;
  if (maxValue <= 0) {
    return;
  }

  const heatPoints = state.filteredRecords
    .map((record) => {
      const value = getMetricValue(record, state.activeMetricKey);
      if (!Number.isFinite(value) || value <= 0) {
        return null;
      }
      const weight = Math.max(0.08, Math.sqrt(value / maxValue));
      return [record.latitude, record.longitude, weight];
    })
    .filter(Boolean);

  if (!heatPoints.length) {
    return;
  }

  state.heatLayer = L.heatLayer(heatPoints, {
    pane: HEAT_PANE,
    radius: 26,
    blur: 18,
    minOpacity: 0.3,
    maxZoom: 7,
    gradient: {
      0.2: "#fee08b",
      0.5: "#f46d43",
      0.85: "#9e0142",
    },
  }).addTo(state.map);
}

function renderPointLayer(metricStats) {
  state.pointLayer.clearLayers();

  if (elements.viewSelect.value === "heat") {
    return;
  }

  const maxValue = metricStats.maxValue ?? 0;
  for (const record of state.filteredRecords) {
    const value = getMetricValue(record, state.activeMetricKey);
    const isActive = record.id === state.activeRecordId;
    const defaultStyle = {
      pane: POINT_PANE,
      renderer: state.canvasRenderer,
      radius: markerRadius(value, maxValue, isActive),
      weight: isActive ? 1.8 : 0.8,
      color: isActive ? "rgba(31, 26, 22, 0.75)" : "rgba(31, 26, 22, 0.38)",
      fillColor: markerColor(record, value, maxValue),
      fillOpacity: Number.isFinite(value) ? (isActive ? 0.92 : 0.82) : 0.46,
    };

    const marker = L.circleMarker([record.latitude, record.longitude], defaultStyle);
    const hoverStyle = {
      weight: Math.max(defaultStyle.weight, 1.5),
      color: "rgba(31, 26, 22, 0.8)",
      radius: defaultStyle.radius + 1.2,
    };

    marker.on("mouseover", () => {
      state.hoverRecordId = record.id;
      marker.setStyle(hoverStyle);
      marker.unbindTooltip();
      marker
        .bindTooltip(buildHoverSummaryHtml(record), {
          direction: "top",
          offset: [0, -10],
          opacity: 1,
          className: "plant-hover-tooltip",
        })
        .openTooltip();
      renderDetail();
    });

    marker.on("mouseout", () => {
      if (state.hoverRecordId === record.id) {
        state.hoverRecordId = "";
      }
      marker.setStyle(defaultStyle);
      marker.closeTooltip();
      marker.unbindTooltip();
      renderDetail();
    });

    marker.on("click", () => {
      focusRecord(record, { flyTo: false });
    });

    state.pointLayer.addLayer(marker);
  }
}

function renderResults(metricStats) {
  const orderedRecords = [...state.filteredRecords].sort((left, right) => {
    const leftValue = getMetricValue(left, state.activeMetricKey) ?? Number.NEGATIVE_INFINITY;
    const rightValue = getMetricValue(right, state.activeMetricKey) ?? Number.NEGATIVE_INFINITY;
    if (rightValue !== leftValue) {
      return rightValue - leftValue;
    }
    return (left.title || "").localeCompare(right.title || "");
  });

  const fragment = document.createDocumentFragment();

  if (!orderedRecords.length) {
    const empty = document.createElement("div");
    empty.className = "microcopy";
    empty.textContent = `No ${state.dataset.metadata.results_label.toLowerCase()} match the current filters.`;
    fragment.append(empty);
  } else {
    const header = document.createElement("div");
    header.className = "microcopy";
    header.textContent = `Showing ${Math.min(25, orderedRecords.length)} of ${integerFormatter.format(orderedRecords.length)} ${state.dataset.metadata.results_label.toLowerCase()}.`;
    fragment.append(header);

    for (const record of orderedRecords.slice(0, 25)) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "result-button";
      if (record.id === state.activeRecordId) {
        button.classList.add("active");
      }

      const title = document.createElement("div");
      title.className = "result-title";
      title.textContent = record.title;

      const subtitle = document.createElement("div");
      subtitle.className = "result-subline";
      subtitle.textContent = record.subtitle || `${record.state || "State unknown"} | ${record.groupValue || "Group unknown"}`;

      const valueLine = document.createElement("div");
      valueLine.className = "result-subline";
      valueLine.textContent = `${metricLabel(state.activeMetricKey)}: ${displayMetricValue(record, state.activeMetricKey)}`;

      button.append(title, subtitle, valueLine);
      button.addEventListener("mouseenter", () => {
        state.hoverRecordId = record.id;
        renderDetail();
      });
      button.addEventListener("mouseleave", () => {
        if (state.hoverRecordId === record.id) {
          state.hoverRecordId = "";
          renderDetail();
        }
      });
      button.addEventListener("click", () => {
        focusRecord(record, { flyTo: true });
      });

      fragment.append(button);
    }
  }

  elements.resultsList.replaceChildren(fragment);

  if (!state.filteredRecords.length) {
    setStatus(`No ${state.dataset.metadata.results_label.toLowerCase()} match the current filters.`);
    return;
  }

  if (!metricStats.countWithMetric) {
    setStatus(`${metricLabel(state.activeMetricKey)} has no numeric values in the current view.`);
    return;
  }

  if (elements.viewSelect.value !== "points" && metricStats.positiveCount === 0) {
    setStatus(`${metricLabel(state.activeMetricKey)} has numeric values, but none are above zero, so the heatmap is empty.`);
    return;
  }

  setStatus(
    `Viewing ${integerFormatter.format(state.filteredRecords.length)} ${state.dataset.metadata.results_label.toLowerCase()} using ${metricLabel(state.activeMetricKey)}.`,
  );
}

function renderDetail() {
  const record = detailRecord();
  if (!record) {
    elements.detailPanel.textContent =
      "Hover or click a point or result row to inspect the active source record.";
    return;
  }

  const previewLabel =
    state.hoverRecordId === record.id ? "Hover preview from the active dataset" : "Selected record";
  const groupLabel = state.dataset.metadata.group_label || "Group";

  const summaryRows = [
    ["Active metric", metricLabel(state.activeMetricKey)],
    ["Metric value", displayMetricValue(record, state.activeMetricKey)],
    ["Record ID", record.id],
    [groupLabel, record.groupValue || "No data"],
    ["State", record.state || "No data"],
    ["County", record.county || "No data"],
    ["Latitude", formatCoordinate(record.latitude)],
    ["Longitude", formatCoordinate(record.longitude)],
  ]
    .map(([label, value]) => buildDetailRowHtml(label, value))
    .join("");

  const fullRow = state.dataset.headers
    .map((header) =>
      buildDetailRowHtml(
        humanizeHeader(header),
        readRowValue(record.row, header),
        normalizeHeader(header) === normalizeHeader(state.activeMetricKey),
      ),
    )
    .join("");

  elements.detailPanel.innerHTML = [
    `<div class="detail-head">`,
    `<strong>${escapeHtml(record.title)}</strong>`,
    `<div class="microcopy">${escapeHtml(previewLabel)}</div>`,
    record.subtitle ? `<div class="microcopy">${escapeHtml(record.subtitle)}</div>` : "",
    `</div>`,
    `<div class="detail-section-label">Active view</div>`,
    `<div class="detail-grid">${summaryRows}</div>`,
    `<div class="detail-section-label">Full source row</div>`,
    `<div class="detail-grid detail-grid--dense">${fullRow}</div>`,
  ].join("");
}

function detailRecord() {
  if (state.hoverRecordId) {
    return state.filteredRecords.find((record) => record.id === state.hoverRecordId) ?? null;
  }
  if (state.activeRecordId) {
    return state.filteredRecords.find((record) => record.id === state.activeRecordId) ?? null;
  }
  return null;
}

function focusRecord(record, options = {}) {
  state.activeRecordId = record.id;
  state.hoverRecordId = "";
  const metricStats = buildMetricStats(state.filteredRecords);
  renderPointLayer(metricStats);
  renderResults(metricStats);
  renderDetail();

  if (options.flyTo) {
    state.map.flyTo([record.latitude, record.longitude], Math.max(state.map.getZoom(), 7), {
      duration: 0.65,
    });
  }
}

function zoomToFiltered() {
  if (!state.filteredRecords.length) {
    return;
  }

  if (state.filteredRecords.length === 1) {
    const [record] = state.filteredRecords;
    state.map.flyTo([record.latitude, record.longitude], 8, { duration: 0.65 });
    return;
  }

  const bounds = L.latLngBounds(state.filteredRecords.map((record) => [record.latitude, record.longitude]));
  state.map.fitBounds(bounds, { padding: [28, 28] });
}

function getMetricValue(record, metricKey) {
  return toNumber(record.metrics?.[metricKey]);
}

function displayMetricValue(record, metricKey) {
  const value = getMetricValue(record, metricKey);
  return Number.isFinite(value) ? formatMetric(value) : "No data";
}

function metricLabel(metricKey) {
  return state.dataset?.metadata.metrics.find((metric) => metric.key === metricKey)?.label ?? metricKey;
}

function preferredMetricKey(dataset) {
  const preferred = dataset.metadata.default_metric_key;
  if (
    preferred &&
    dataset.metadata.metrics.some((metric) => metric.key === preferred) &&
    dataset.records.some((record) => Number.isFinite(getMetricValue(record, preferred)))
  ) {
    return preferred;
  }
  return dataset.metadata.metrics[0]?.key ?? "";
}

function markerRadius(value, maxValue, isActive = false) {
  const baseRadius = !Number.isFinite(value) || maxValue <= 0 ? 4.2 : 4 + Math.sqrt(value / maxValue) * 10;
  return isActive ? baseRadius + 1.2 : baseRadius;
}

function markerColor(record, value, maxValue) {
  if (!Number.isFinite(value) || maxValue <= 0) {
    return groupColor(record.groupValue);
  }
  const ratio = Math.max(0, Math.min(1, Math.sqrt(value / maxValue)));
  return interpolateColor("#fee08b", "#9e0142", ratio);
}

function groupColor(value) {
  const normalized = stringValue(value);
  if (!normalized) {
    return "#8d7b68";
  }
  if (SPECIAL_GROUP_COLORS[normalized]) {
    return SPECIAL_GROUP_COLORS[normalized];
  }

  const palette = [
    "#5f8d4e",
    "#3a7ca5",
    "#b03a2e",
    "#7c5c47",
    "#9b6a6c",
    "#8a9b0f",
    "#7d6c97",
    "#2f6b8f",
    "#c97c5d",
  ];
  let hash = 0;
  for (const character of normalized) {
    hash = (hash * 31 + character.charCodeAt(0)) % 2147483647;
  }
  return palette[Math.abs(hash) % palette.length];
}

function buildHoverSummaryHtml(record) {
  return [
    `<div class="popup-title">${escapeHtml(record.title)}</div>`,
    record.subtitle ? `<div class="popup-line">${escapeHtml(record.subtitle)}</div>` : "",
    `<div class="popup-line">${escapeHtml(metricLabel(state.activeMetricKey))}: ${escapeHtml(displayMetricValue(record, state.activeMetricKey))}</div>`,
    `<div class="popup-line">${escapeHtml(record.groupValue || "Unspecified")}</div>`,
  ].join("");
}

function buildDetailRowHtml(label, value, isHighlighted = false) {
  return [
    `<div class="detail-row${isHighlighted ? " is-highlighted" : ""}">`,
    `<span>${escapeHtml(label)}</span>`,
    `<strong>${escapeHtml(value)}</strong>`,
    `</div>`,
  ].join("");
}

function readRowValue(row, header) {
  return stringValue(row?.[header]) || "No data";
}

function buildSearchText(row) {
  return Object.values(row ?? {})
    .map((value) => stringValue(value))
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

async function fetchJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} for ${url}`);
  }
  return response.json();
}

function stringValue(value) {
  if (value === null || value === undefined) {
    return "";
  }
  return String(value).trim();
}

function parseInputNumber(value) {
  if (typeof value !== "string") {
    return Number.isFinite(value) ? value : null;
  }

  const normalized = value.trim().replace(/[$,%\s]/g, "").replace(/,/g, "");
  if (!normalized) {
    return null;
  }

  const number = Number(normalized);
  return Number.isFinite(number) ? number : null;
}

function toNumber(value) {
  if (value === null || value === undefined || value === "" || value === "No data") {
    return null;
  }
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function formatMetric(value) {
  const absoluteValue = Math.abs(value);
  if (absoluteValue >= 1000) {
    return integerFormatter.format(value);
  }
  if (absoluteValue > 0 && absoluteValue < 0.01) {
    return value.toExponential(2);
  }
  return numberFormatter.format(value);
}

function formatCoordinate(value) {
  return Number.isFinite(value) ? value.toFixed(4) : "No data";
}

function normalizeHeader(value) {
  return String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

function humanizeHeader(header) {
  const normalizedHeader = normalizeHeader(header);
  return HEADER_LABEL_OVERRIDES[normalizedHeader] ?? titleizeKey(normalizedHeader);
}

function titleizeKey(value) {
  const uppercaseTokens = new Map([
    ["co2", "CO2"],
    ["co2e", "CO2e"],
    ["nox", "NOx"],
    ["so2", "SO2"],
    ["n2o", "N2O"],
    ["ch4", "CH4"],
    ["ghgrp", "GHGRP"],
    ["frs", "FRS"],
    ["naics", "NAICS"],
    ["mtco2e", "MTCO2e"],
    ["mw", "MW"],
    ["sq", "Sq"],
    ["sqmi", "Sq Mi"],
    ["zip", "ZIP"],
    ["id", "ID"],
    ["ids", "IDs"],
    ["pct", "Pct"],
    ["2024", "2024"],
    ["2023", "2023"],
  ]);

  return value
    .split("_")
    .filter(Boolean)
    .map((token) => uppercaseTokens.get(token) ?? token.charAt(0).toUpperCase() + token.slice(1))
    .join(" ");
}

function singularizeLabel(value) {
  const text = stringValue(value);
  if (text.endsWith("ies")) {
    return `${text.slice(0, -3)}y`;
  }
  if (text.endsWith("s")) {
    return text.slice(0, -1);
  }
  return text || "Record";
}

function setStatus(message, tone = "info") {
  elements.statusPill.textContent = message;
  elements.statusPill.dataset.tone = tone;
}

function interpolateColor(startHex, endHex, ratio) {
  const start = hexToRgb(startHex);
  const end = hexToRgb(endHex);
  const mix = (left, right) => Math.round(left + (right - left) * ratio);
  return `rgb(${mix(start.r, end.r)}, ${mix(start.g, end.g)}, ${mix(start.b, end.b)})`;
}

function hexToRgb(hex) {
  const sanitized = hex.replace("#", "");
  return {
    r: Number.parseInt(sanitized.slice(0, 2), 16),
    g: Number.parseInt(sanitized.slice(2, 4), 16),
    b: Number.parseInt(sanitized.slice(4, 6), 16),
  };
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}
