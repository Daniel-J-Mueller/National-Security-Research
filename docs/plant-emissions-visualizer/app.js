const MANIFEST_URL = "../../data/private/visualizer/visualizer_manifest.json";
const HEAT_PANE = "heatPane";
const POINT_PANE = "pointPane";

const LAYER_COLORS = [
  "#b03a2e",
  "#2f6b8f",
  "#5f8d4e",
  "#7d5ba6",
  "#d47f2f",
  "#a14f67",
  "#3f7c73",
  "#886247",
];

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
  activeLayers: [],
  layerSequence: 0,
  focusedLayerId: "",
  activeRecordKey: "",
  hoverRecordKey: "",
  showNulls: false,
  controlPane: "simple",
  simpleDatasetKey: "",
  map: null,
  canvasRenderer: null,
};

const numberFormatter = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });
const integerFormatter = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

const elements = {
  simplePaneButton: document.getElementById("simple-pane-button"),
  advancedPaneButton: document.getElementById("advanced-pane-button"),
  simplePane: document.getElementById("simple-pane"),
  advancedPane: document.getElementById("advanced-pane"),
  simpleDatasetSelect: document.getElementById("simple-dataset-select"),
  simpleMetricSelect: document.getElementById("simple-metric-select"),
  addLayer: document.getElementById("add-layer"),
  zoomVisible: document.getElementById("zoom-visible"),
  clearLayers: document.getElementById("clear-layers"),
  focusLayerSelect: document.getElementById("focus-layer-select"),
  advancedDatasetSelect: document.getElementById("advanced-dataset-select"),
  advancedMetricSelect: document.getElementById("advanced-metric-select"),
  viewSelect: document.getElementById("view-select"),
  stateSelect: document.getElementById("state-select"),
  groupSelect: document.getElementById("group-select"),
  groupLabel: document.getElementById("group-filter-label"),
  searchLabel: document.getElementById("search-label"),
  searchInput: document.getElementById("search-input"),
  minimumInput: document.getElementById("minimum-input"),
  showNullsToggle: document.getElementById("show-nulls-toggle"),
  resetFilters: document.getElementById("reset-filters"),
  activeLayerList: document.getElementById("active-layer-list"),
  layerCount: document.getElementById("layer-count"),
  activeLayerCount: document.getElementById("active-layer-count"),
  visibleCount: document.getElementById("visible-count"),
  metricTotal: document.getElementById("metric-total"),
  metricMax: document.getElementById("metric-max"),
  metricName: document.getElementById("metric-name"),
  layerLegend: document.getElementById("layer-legend"),
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
        sharded: Boolean(dataset.sharded),
        shardCount: toNumber(dataset.shard_count),
      }))
      .filter((dataset) => dataset.key && dataset.path);

    if (!state.manifest.length) {
      throw new Error("No valid dataset entries were found in visualizer_manifest.json.");
    }

    populateDatasetOptions(elements.simpleDatasetSelect);
    populateDatasetOptions(elements.advancedDatasetSelect);

    state.simpleDatasetKey = state.manifest[0].key;
    elements.simpleDatasetSelect.value = state.simpleDatasetKey;
    await syncSimpleMetricOptions(state.simpleDatasetKey);

    setControlPane("simple");
    await addLayer(
      {
        datasetKey: state.simpleDatasetKey,
        metricKey: elements.simpleMetricSelect.value,
      },
      { allowDuplicate: true, fitBounds: true },
    );
  } catch (error) {
    console.error(error);
    setStatus(
      "Could not load the visualizer manifest. Serve the repo root over HTTP before opening this page.",
      "error",
    );
  }
}

function bindEvents() {
  for (const button of [elements.simplePaneButton, elements.advancedPaneButton]) {
    button.addEventListener("click", () => {
      setControlPane(button.dataset.pane);
    });
  }

  elements.simpleDatasetSelect.addEventListener("change", async () => {
    state.simpleDatasetKey = elements.simpleDatasetSelect.value;
    await syncSimpleMetricOptions(state.simpleDatasetKey);
  });

  elements.addLayer.addEventListener("click", async () => {
    await addLayer({
      datasetKey: elements.simpleDatasetSelect.value,
      metricKey: elements.simpleMetricSelect.value,
    });
  });

  elements.zoomVisible.addEventListener("click", () => {
    zoomToRecords(collectVisibleRecords());
  });

  elements.clearLayers.addEventListener("click", async () => {
    await clearAllLayers();
  });

  elements.focusLayerSelect.addEventListener("change", async () => {
    await focusLayer(elements.focusLayerSelect.value);
  });

  elements.advancedDatasetSelect.addEventListener("change", async () => {
    await updateFocusedLayerDataset(elements.advancedDatasetSelect.value);
  });

  elements.advancedMetricSelect.addEventListener("change", () => {
    const layer = focusedLayer();
    if (!layer) {
      return;
    }

    layer.metricKey = resolveMetricKey(datasetForLayer(layer), elements.advancedMetricSelect.value);
    clearLayerRecordSelection(layer.id);
    refreshView({ fitBounds: true });
  });

  elements.viewSelect.addEventListener("change", () => {
    const layer = focusedLayer();
    if (!layer) {
      return;
    }

    layer.viewMode = elements.viewSelect.value;
    refreshView();
  });

  elements.stateSelect.addEventListener("change", () => {
    const layer = focusedLayer();
    if (!layer) {
      return;
    }

    layer.stateFilter = elements.stateSelect.value;
    clearLayerRecordSelection(layer.id);
    refreshView({ fitBounds: true });
  });

  elements.groupSelect.addEventListener("change", () => {
    const layer = focusedLayer();
    if (!layer) {
      return;
    }

    layer.groupFilter = elements.groupSelect.value;
    clearLayerRecordSelection(layer.id);
    refreshView({ fitBounds: true });
  });

  elements.searchInput.addEventListener("input", () => {
    const layer = focusedLayer();
    if (!layer) {
      return;
    }

    layer.searchTerm = elements.searchInput.value;
    clearLayerRecordSelection(layer.id);
    refreshView();
  });

  elements.minimumInput.addEventListener("input", () => {
    const layer = focusedLayer();
    if (!layer) {
      return;
    }

    layer.minimumValue = elements.minimumInput.value;
    clearLayerRecordSelection(layer.id);
    refreshView();
  });

  elements.showNullsToggle.addEventListener("change", () => {
    state.showNulls = elements.showNullsToggle.checked;
    clearAllRecordSelection();
    refreshView({ fitBounds: true });
  });

  elements.resetFilters.addEventListener("click", () => {
    const layer = focusedLayer();
    if (!layer) {
      return;
    }

    layer.stateFilter = "";
    layer.groupFilter = "";
    layer.searchTerm = "";
    layer.minimumValue = "";
    elements.stateSelect.value = "";
    elements.groupSelect.value = "";
    elements.searchInput.value = "";
    elements.minimumInput.value = "";
    clearLayerRecordSelection(layer.id);
    refreshView({ fitBounds: true });
  });

  elements.activeLayerList.addEventListener("click", (event) => {
    const actionButton = event.target.closest("[data-layer-action]");
    if (!actionButton) {
      return;
    }

    const layerId = actionButton.dataset.layerId;
    if (!layerId) {
      return;
    }

    const action = actionButton.dataset.layerAction;
    if (action === "focus") {
      void focusLayer(layerId);
      return;
    }

    if (action === "zoom") {
      const layer = layerById(layerId);
      if (layer) {
        zoomToRecords(layer.filteredRecords);
      }
      return;
    }

    if (action === "remove") {
      void removeLayer(layerId);
    }
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
}

async function addLayer(request, options = {}) {
  const datasetKey = stringValue(request.datasetKey);
  if (!datasetKey) {
    return null;
  }

  setStatus(`Loading ${manifestLabel(datasetKey)}...`);

  const dataset = await loadDataset(datasetKey);
  const metricKey = resolveMetricKey(dataset, request.metricKey);
  const existingLayer = state.activeLayers.find(
    (layer) => layer.datasetKey === dataset.key && layer.metricKey === metricKey,
  );

  if (existingLayer && !options.allowDuplicate) {
    await focusLayer(existingLayer.id);
    setStatus(`${layerDisplayLabel(existingLayer)} is already active.`);
    return existingLayer;
  }

  const colorIndex = state.layerSequence % LAYER_COLORS.length;
  state.layerSequence += 1;

  const layer = {
    id: `layer-${state.layerSequence}`,
    datasetKey: dataset.key,
    metricKey,
    viewMode: state.activeLayers.length === 0 ? "both" : "points",
    stateFilter: "",
    groupFilter: "",
    searchTerm: "",
    minimumValue: "",
    filteredRecords: [],
    metricStats: emptyMetricStats(),
    color: LAYER_COLORS[colorIndex],
    pointLayer: L.layerGroup().addTo(state.map),
    heatLayer: null,
  };

  state.activeLayers.push(layer);
  state.focusedLayerId = layer.id;
  clearAllRecordSelection();
  await syncAdvancedControls();
  refreshView({ fitBounds: options.fitBounds !== false });
  return layer;
}

async function removeLayer(layerId) {
  const index = state.activeLayers.findIndex((layer) => layer.id === layerId);
  if (index === -1) {
    return;
  }

  const [layer] = state.activeLayers.splice(index, 1);
  disposeLayer(layer);
  clearLayerRecordSelection(layer.id);

  if (state.focusedLayerId === layer.id) {
    state.focusedLayerId = state.activeLayers[0]?.id ?? "";
  }

  await syncAdvancedControls();
  refreshView({ fitBounds: true });
}

async function clearAllLayers() {
  for (const layer of state.activeLayers) {
    disposeLayer(layer);
  }

  state.activeLayers = [];
  state.focusedLayerId = "";
  clearAllRecordSelection();
  await syncAdvancedControls();
  refreshView();
}

async function focusLayer(layerId) {
  const layer = layerById(layerId);
  if (!layer) {
    return;
  }

  state.focusedLayerId = layer.id;
  if (!recordKeyBelongsToLayer(state.activeRecordKey, layer.id)) {
    state.activeRecordKey = "";
  }
  if (!recordKeyBelongsToLayer(state.hoverRecordKey, layer.id)) {
    state.hoverRecordKey = "";
  }

  await syncAdvancedControls();
  refreshView();
}

async function updateFocusedLayerDataset(datasetKey) {
  const layer = focusedLayer();
  if (!layer || !datasetKey) {
    return;
  }

  setStatus(`Loading ${manifestLabel(datasetKey)}...`);

  const dataset = await loadDataset(datasetKey);
  layer.datasetKey = dataset.key;
  layer.metricKey = preferredMetricKey(dataset);
  layer.stateFilter = "";
  layer.groupFilter = "";
  layer.searchTerm = "";
  layer.minimumValue = "";
  clearLayerRecordSelection(layer.id);
  await syncAdvancedControls();
  refreshView({ fitBounds: true });
}

async function loadDataset(datasetKey) {
  if (state.datasetCache.has(datasetKey)) {
    return state.datasetCache.get(datasetKey);
  }

  const manifestEntry = manifestEntryByKey(datasetKey);
  if (!manifestEntry) {
    throw new Error(`Missing dataset entry for ${datasetKey}`);
  }

  const payload = await fetchDatasetPayload(manifestEntry);
  if (!payload || !Array.isArray(payload.records) || !payload.records.length) {
    throw new Error(`${manifestEntry.path} does not contain any mapped records.`);
  }

  const dataset = hydrateDataset(payload, manifestEntry);
  state.datasetCache.set(datasetKey, dataset);
  return dataset;
}

async function fetchDatasetPayload(manifestEntry) {
  const payload = await fetchJson(manifestEntry.path);
  if (!payload?.sharded) {
    return payload;
  }

  if (!Array.isArray(payload.shards) || !payload.shards.length) {
    throw new Error(`${manifestEntry.path} is marked as sharded but does not list any shards.`);
  }

  const shardPayloads = await Promise.all(payload.shards.map(async (shard) => {
    const shardPath = stringValue(shard.path);
    if (!shardPath) {
      throw new Error(`${manifestEntry.path} contains a shard without a path.`);
    }

    const shardPayload = await fetchJson(shardPath);
    if (!Array.isArray(shardPayload.records)) {
      throw new Error(`${shardPath} does not contain records.`);
    }
    return shardPayload;
  }));

  return {
    ...payload,
    records: shardPayloads.flatMap((shardPayload) => shardPayload.records),
  };
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
      default_metric_key:
        stringValue(metadata.default_metric_key) ||
        manifestEntry.defaultMetricKey ||
        availableMetrics[0].key,
    },
  };
}

function refreshView(options = {}) {
  ensureFocusedLayerExists();

  for (const layer of state.activeLayers) {
    layer.filteredRecords = applyFilters(layer);
    layer.metricStats = buildMetricStats(layer.filteredRecords, layer.metricKey);
  }

  pruneSelectedRecords();

  const orderedLayers = renderOrder();
  for (const layer of orderedLayers) {
    renderHeatLayer(layer);
    renderPointLayer(layer);
  }

  renderActiveLayerList();
  renderSummary();
  renderResults();
  renderDetail();
  renderStatus();

  if (options.fitBounds) {
    zoomToRecords(collectVisibleRecords());
  }
}

function applyFilters(layer) {
  const dataset = datasetForLayer(layer);
  if (!dataset) {
    return [];
  }

  const selectedState = stringValue(layer.stateFilter);
  const selectedGroup = stringValue(layer.groupFilter);
  const searchTerm = stringValue(layer.searchTerm).toLowerCase();
  const minimumValue = parseInputNumber(layer.minimumValue);

  return dataset.records.filter((record) => {
    const metricValue = getMetricValue(record, layer.metricKey);

    if (!state.showNulls && !Number.isFinite(metricValue)) {
      return false;
    }
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
      if (!Number.isFinite(metricValue) || metricValue < minimumValue) {
        return false;
      }
    }
    return true;
  });
}

function buildMetricStats(records, metricKey) {
  const values = [];
  let total = 0;
  let maxRecord = null;
  let maxValue = Number.NEGATIVE_INFINITY;
  let positiveCount = 0;

  for (const record of records) {
    const value = getMetricValue(record, metricKey);
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

function renderHeatLayer(layer) {
  if (layer.heatLayer) {
    state.map.removeLayer(layer.heatLayer);
    layer.heatLayer = null;
  }

  if (layer.viewMode === "points" || typeof L.heatLayer !== "function") {
    return;
  }

  const maxValue = layer.metricStats.maxValue ?? 0;
  if (maxValue <= 0) {
    return;
  }

  const heatPoints = layer.filteredRecords
    .map((record) => {
      const value = getMetricValue(record, layer.metricKey);
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

  layer.heatLayer = L.heatLayer(heatPoints, {
    pane: HEAT_PANE,
    radius: 24,
    blur: 18,
    minOpacity: 0.24,
    maxZoom: 7,
    gradient: buildHeatGradient(layer.color),
  }).addTo(state.map);
}

function renderPointLayer(layer) {
  layer.pointLayer.clearLayers();

  if (layer.viewMode === "heat") {
    return;
  }

  const maxValue = layer.metricStats.maxValue ?? 0;
  const isFocused = layer.id === state.focusedLayerId;

  for (const record of layer.filteredRecords) {
    const value = getMetricValue(record, layer.metricKey);
    const recordKey = toRecordKey(layer.id, record.id);
    const isHighlighted = recordKey === state.activeRecordKey || recordKey === state.hoverRecordKey;
    const hasMetric = Number.isFinite(value);

    const defaultStyle = {
      pane: POINT_PANE,
      renderer: state.canvasRenderer,
      radius: markerRadius(value, maxValue, isHighlighted),
      weight: isHighlighted ? 2 : isFocused ? 1.2 : 0.8,
      color: isHighlighted
        ? "rgba(31, 26, 22, 0.84)"
        : isFocused
          ? "rgba(31, 26, 22, 0.56)"
          : "rgba(31, 26, 22, 0.3)",
      fillColor: markerColor(layer, value, maxValue),
      fillOpacity: hasMetric ? (isFocused ? 0.84 : 0.68) : 0.24,
    };

    const marker = L.circleMarker([record.latitude, record.longitude], defaultStyle);
    const hoverStyle = {
      weight: Math.max(defaultStyle.weight, 1.8),
      color: "rgba(31, 26, 22, 0.88)",
      radius: defaultStyle.radius + 1.2,
    };

    marker.on("mouseover", () => {
      state.hoverRecordKey = recordKey;
      marker.setStyle(hoverStyle);
      marker.unbindTooltip();
      marker
        .bindTooltip(buildHoverSummaryHtml(layer, record), {
          direction: "top",
          offset: [0, -10],
          opacity: 1,
          className: "plant-hover-tooltip",
        })
        .openTooltip();
      renderDetail();
    });

    marker.on("mouseout", () => {
      if (state.hoverRecordKey === recordKey) {
        state.hoverRecordKey = "";
      }
      marker.setStyle(defaultStyle);
      marker.closeTooltip();
      marker.unbindTooltip();
      renderDetail();
    });

    marker.on("click", () => {
      focusRecord(layer, record, { flyTo: false });
    });

    layer.pointLayer.addLayer(marker);
  }
}

function renderSummary() {
  const layer = focusedLayer();
  elements.activeLayerCount.textContent = integerFormatter.format(state.activeLayers.length);
  renderLayerLegend();

  if (!layer) {
    elements.visibleCount.textContent = "0";
    elements.metricTotal.textContent = "No data";
    elements.metricMax.textContent = "No data";
    elements.metricName.textContent = "Add a characteristic";
    elements.datasetDescription.textContent =
      "Add one or more characteristics to compare emissions, ores, radiation, population, and agriculture on the same map.";
    elements.resultsHeading.textContent = "Results";
    elements.detailHeading.textContent = "Record detail";
    document.title = "Strategic Resource Visualizer";
    return;
  }

  const dataset = datasetForLayer(layer);
  const stats = layer.metricStats;
  const metricLabelText = metricLabel(layer.metricKey, layer);

  elements.visibleCount.textContent = integerFormatter.format(layer.filteredRecords.length);
  elements.metricTotal.textContent = stats.countWithMetric ? formatMetric(stats.total) : "No data";
  elements.metricMax.textContent = stats.maxRecord
    ? `${stats.maxRecord.title} (${formatMetric(stats.maxValue)})`
    : "No data";
  elements.metricName.textContent = layerDisplayLabel(layer);
  elements.datasetDescription.textContent = `${dataset.metadata.description} Focused layer: ${layerDisplayLabel(layer)}.`;
  elements.resultsHeading.textContent = `${dataset.metadata.results_label} by ${metricLabelText}`;
  elements.detailHeading.textContent = `${singularizeLabel(dataset.metadata.results_label)} detail`;
  document.title =
    state.activeLayers.length > 1
      ? `${layerDisplayLabel(layer)} + ${state.activeLayers.length - 1} more | Strategic Resource Visualizer`
      : `${layerDisplayLabel(layer)} | Strategic Resource Visualizer`;
}

function renderLayerLegend() {
  const fragment = document.createDocumentFragment();

  if (!state.activeLayers.length) {
    const empty = document.createElement("div");
    empty.className = "microcopy";
    empty.textContent = "No active layers yet.";
    fragment.append(empty);
    elements.layerLegend.replaceChildren(fragment);
    return;
  }

  for (const layer of state.activeLayers) {
    const item = document.createElement("div");
    item.className = "layer-legend-item";

    const dot = document.createElement("span");
    dot.className = "layer-dot";
    dot.style.backgroundColor = layer.color;

    const text = document.createElement("span");
    text.textContent =
      layer.id === state.focusedLayerId
        ? `${layerDisplayLabel(layer)} (focused)`
        : layerDisplayLabel(layer);

    item.append(dot, text);
    fragment.append(item);
  }

  elements.layerLegend.replaceChildren(fragment);
}

function renderActiveLayerList() {
  elements.layerCount.textContent = `${integerFormatter.format(state.activeLayers.length)} active`;

  const fragment = document.createDocumentFragment();

  if (!state.activeLayers.length) {
    const empty = document.createElement("div");
    empty.className = "microcopy";
    empty.textContent = "Add a characteristic to begin stacking layers.";
    fragment.append(empty);
    elements.activeLayerList.replaceChildren(fragment);
    return;
  }

  for (const layer of state.activeLayers) {
    const dataset = datasetForLayer(layer);
    const card = document.createElement("div");
    card.className = "layer-card";
    if (layer.id === state.focusedLayerId) {
      card.classList.add("is-focused");
    }

    const top = document.createElement("div");
    top.className = "layer-card-top";

    const mainButton = document.createElement("button");
    mainButton.type = "button";
    mainButton.className = "layer-main-button";
    mainButton.dataset.layerAction = "focus";
    mainButton.dataset.layerId = layer.id;

    const titleRow = document.createElement("div");
    titleRow.className = "layer-title-row";

    const dot = document.createElement("span");
    dot.className = "layer-dot";
    dot.style.backgroundColor = layer.color;

    const titleText = document.createElement("div");
    titleText.className = "layer-title";
    titleText.textContent = layerDisplayLabel(layer);

    titleRow.append(dot, titleText);
    mainButton.append(titleRow);

    const meta = document.createElement("div");
    meta.className = "layer-meta";
    meta.textContent = `${integerFormatter.format(layer.filteredRecords.length)} ${dataset.metadata.results_label.toLowerCase()} visible | ${viewLabel(layer.viewMode)}`;
    mainButton.append(meta);

    const note = document.createElement("div");
    note.className = "layer-card-note";
    note.textContent = buildLayerFilterSummary(layer);
    mainButton.append(note);

    const actions = document.createElement("div");
    actions.className = "layer-actions";

    const focusButton = document.createElement("button");
    focusButton.type = "button";
    focusButton.dataset.layerAction = "focus";
    focusButton.dataset.layerId = layer.id;
    focusButton.textContent = layer.id === state.focusedLayerId ? "Focused" : "Focus";

    const zoomButton = document.createElement("button");
    zoomButton.type = "button";
    zoomButton.dataset.layerAction = "zoom";
    zoomButton.dataset.layerId = layer.id;
    zoomButton.textContent = "Zoom";

    const removeButton = document.createElement("button");
    removeButton.type = "button";
    removeButton.dataset.layerAction = "remove";
    removeButton.dataset.layerId = layer.id;
    removeButton.textContent = "Remove";

    actions.append(focusButton, zoomButton, removeButton);
    top.append(mainButton, actions);
    card.append(top);
    fragment.append(card);
  }

  elements.activeLayerList.replaceChildren(fragment);
}

function renderResults() {
  const layer = focusedLayer();
  const fragment = document.createDocumentFragment();

  if (!layer) {
    const empty = document.createElement("div");
    empty.className = "microcopy";
    empty.textContent = "Results will appear here once a characteristic layer is active.";
    fragment.append(empty);
    elements.resultsList.replaceChildren(fragment);
    return;
  }

  const dataset = datasetForLayer(layer);
  const orderedRecords = [...layer.filteredRecords].sort((left, right) => {
    const leftValue = getMetricValue(left, layer.metricKey) ?? Number.NEGATIVE_INFINITY;
    const rightValue = getMetricValue(right, layer.metricKey) ?? Number.NEGATIVE_INFINITY;
    if (rightValue !== leftValue) {
      return rightValue - leftValue;
    }
    return (left.title || "").localeCompare(right.title || "");
  });

  if (!orderedRecords.length) {
    const empty = document.createElement("div");
    empty.className = "microcopy";
    empty.textContent = `No ${dataset.metadata.results_label.toLowerCase()} match the current filters for ${layerDisplayLabel(layer)}.`;
    fragment.append(empty);
    elements.resultsList.replaceChildren(fragment);
    return;
  }

  const header = document.createElement("div");
  header.className = "microcopy";
  header.textContent = `Focused layer: ${layerDisplayLabel(layer)}. Showing ${Math.min(25, orderedRecords.length)} of ${integerFormatter.format(orderedRecords.length)} ${dataset.metadata.results_label.toLowerCase()}.`;
  fragment.append(header);

  for (const record of orderedRecords.slice(0, 25)) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "result-button";

    const recordKey = toRecordKey(layer.id, record.id);
    if (recordKey === state.activeRecordKey) {
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
    valueLine.textContent = `${metricLabel(layer.metricKey, layer)}: ${displayMetricValue(record, layer.metricKey)}`;

    button.append(title, subtitle, valueLine);
    button.addEventListener("mouseenter", () => {
      state.hoverRecordKey = recordKey;
      renderDetail();
    });
    button.addEventListener("mouseleave", () => {
      if (state.hoverRecordKey === recordKey) {
        state.hoverRecordKey = "";
        renderDetail();
      }
    });
    button.addEventListener("click", () => {
      focusRecord(layer, record, { flyTo: true });
    });

    fragment.append(button);
  }

  elements.resultsList.replaceChildren(fragment);
}

function renderDetail() {
  const target = detailTarget();
  if (!target) {
    elements.detailPanel.textContent =
      "Hover or click a point or result row to inspect the active source record.";
    return;
  }

  const { layer, record, recordKey } = target;
  const dataset = datasetForLayer(layer);
  const previewLabel =
    state.hoverRecordKey === recordKey
      ? `Hover preview from ${layerDisplayLabel(layer)}`
      : `Selected record from ${layerDisplayLabel(layer)}`;
  const groupLabel = dataset.metadata.group_label || "Group";

  const summaryRows = [
    ["Layer", layerDisplayLabel(layer)],
    ["Active metric", metricLabel(layer.metricKey, layer)],
    ["Metric value", displayMetricValue(record, layer.metricKey)],
    ["Record ID", record.id],
    [groupLabel, record.groupValue || "No data"],
    ["State", record.state || "No data"],
    ["County", record.county || "No data"],
    ["Latitude", formatCoordinate(record.latitude)],
    ["Longitude", formatCoordinate(record.longitude)],
  ]
    .map(([label, value]) => buildDetailRowHtml(label, value))
    .join("");

  const fullRow = dataset.headers
    .map((header) =>
      buildDetailRowHtml(
        humanizeHeader(header),
        readRowValue(record.row, header),
        normalizeHeader(header) === normalizeHeader(layer.metricKey),
      ),
    )
    .join("");

  elements.detailPanel.innerHTML = [
    `<div class="detail-head">`,
    `<strong>${escapeHtml(record.title)}</strong>`,
    `<div class="microcopy">${escapeHtml(previewLabel)}</div>`,
    record.subtitle ? `<div class="microcopy">${escapeHtml(record.subtitle)}</div>` : "",
    `</div>`,
    `<div class="detail-section-label">Focused view</div>`,
    `<div class="detail-grid">${summaryRows}</div>`,
    `<div class="detail-section-label">Full source row</div>`,
    `<div class="detail-grid detail-grid--dense">${fullRow}</div>`,
  ].join("");
}

function renderStatus() {
  const layer = focusedLayer();
  if (!layer) {
    setStatus("Add a characteristic to start comparing layers.");
    return;
  }

  const dataset = datasetForLayer(layer);
  const metricName = metricLabel(layer.metricKey, layer);

  if (!layer.filteredRecords.length) {
    setStatus(`No ${dataset.metadata.results_label.toLowerCase()} match the current filters for ${layerDisplayLabel(layer)}.`);
    return;
  }

  if (layer.viewMode !== "points" && layer.metricStats.positiveCount === 0) {
    setStatus(`${metricName} has no values above zero in ${layerDisplayLabel(layer)}, so its heatmap is empty.`);
    return;
  }

  if (state.showNulls && layer.metricStats.countWithMetric < layer.filteredRecords.length) {
    setStatus(
      `Viewing ${integerFormatter.format(layer.filteredRecords.length)} ${dataset.metadata.results_label.toLowerCase()} in ${layerDisplayLabel(layer)}. Null metric values are included for debugging.`,
    );
    return;
  }

  setStatus(
    `Viewing ${integerFormatter.format(layer.filteredRecords.length)} ${dataset.metadata.results_label.toLowerCase()} in ${layerDisplayLabel(layer)}.`,
  );
}

function focusRecord(layer, record, options = {}) {
  state.focusedLayerId = layer.id;
  state.activeRecordKey = toRecordKey(layer.id, record.id);
  state.hoverRecordKey = "";
  void syncAdvancedControls();
  refreshView();

  if (options.flyTo) {
    state.map.flyTo([record.latitude, record.longitude], Math.max(state.map.getZoom(), 7), {
      duration: 0.65,
    });
  }
}

function zoomToRecords(records) {
  if (!records.length) {
    return;
  }

  if (records.length === 1) {
    const [record] = records;
    state.map.flyTo([record.latitude, record.longitude], 8, { duration: 0.65 });
    return;
  }

  const bounds = L.latLngBounds(records.map((record) => [record.latitude, record.longitude]));
  state.map.fitBounds(bounds, { padding: [28, 28] });
}

async function syncSimpleMetricOptions(datasetKey, preferredMetricKey = "") {
  if (!datasetKey) {
    replaceSelectOptions(elements.simpleMetricSelect, [], "No characteristics available");
    return;
  }

  const dataset = await loadDataset(datasetKey);
  populateMetricOptions(elements.simpleMetricSelect, dataset, resolveMetricKey(dataset, preferredMetricKey));
}

async function syncAdvancedControls() {
  populateDatasetOptions(elements.advancedDatasetSelect);
  populateFocusLayerOptions();
  elements.showNullsToggle.checked = state.showNulls;

  const layer = focusedLayer();
  const advancedControls = [
    elements.advancedDatasetSelect,
    elements.advancedMetricSelect,
    elements.viewSelect,
    elements.stateSelect,
    elements.groupSelect,
    elements.searchInput,
    elements.minimumInput,
    elements.resetFilters,
  ];

  if (!layer) {
    for (const control of advancedControls) {
      control.disabled = true;
    }
    replaceSelectOptions(elements.advancedMetricSelect, [], "No active layer");
    replaceSelectOptions(elements.stateSelect, [], "All states");
    replaceSelectOptions(elements.groupSelect, [], "All groups");
    elements.groupLabel.textContent = "Group";
    elements.searchLabel.textContent = "Search records";
    elements.searchInput.value = "";
    elements.searchInput.placeholder = "Search the focused layer";
    elements.minimumInput.value = "";
    elements.viewSelect.value = "points";
    return;
  }

  const dataset = datasetForLayer(layer) ?? (await loadDataset(layer.datasetKey));
  for (const control of advancedControls) {
    control.disabled = false;
  }

  elements.focusLayerSelect.value = layer.id;
  elements.advancedDatasetSelect.value = dataset.key;
  populateMetricOptions(elements.advancedMetricSelect, dataset, layer.metricKey);
  elements.viewSelect.value = layer.viewMode;

  const states = [...new Set(dataset.records.map((record) => record.state).filter(Boolean))].sort();
  const groups = [...new Set(dataset.records.map((record) => record.groupValue).filter(Boolean))].sort();

  replaceSelectOptions(elements.stateSelect, states, "All states");
  replaceSelectOptions(
    elements.groupSelect,
    groups,
    `All ${dataset.metadata.group_label.toLowerCase()} groups`,
  );

  if (states.includes(layer.stateFilter)) {
    elements.stateSelect.value = layer.stateFilter;
  }
  if (groups.includes(layer.groupFilter)) {
    elements.groupSelect.value = layer.groupFilter;
  }

  elements.groupLabel.textContent = dataset.metadata.group_label;
  elements.searchLabel.textContent = `Search ${dataset.metadata.results_label.toLowerCase()}`;
  elements.searchInput.placeholder = dataset.metadata.search_placeholder;
  elements.searchInput.value = layer.searchTerm;
  elements.minimumInput.value = layer.minimumValue;
}

function populateDatasetOptions(select) {
  const previousValue = select.value;
  select.replaceChildren();

  for (const dataset of state.manifest) {
    const option = document.createElement("option");
    option.value = dataset.key;
    option.textContent = dataset.label;
    select.append(option);
  }

  if (state.manifest.some((dataset) => dataset.key === previousValue)) {
    select.value = previousValue;
  }
}

function populateMetricOptions(select, dataset, selectedMetricKey = "") {
  select.replaceChildren();

  for (const metric of dataset.metadata.metrics) {
    const option = document.createElement("option");
    option.value = metric.key;
    option.textContent = metric.label;
    select.append(option);
  }

  const resolvedMetric = resolveMetricKey(dataset, selectedMetricKey);
  select.value = resolvedMetric;
}

function populateFocusLayerOptions() {
  elements.focusLayerSelect.replaceChildren();

  if (!state.activeLayers.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No active layers";
    elements.focusLayerSelect.append(option);
    return;
  }

  for (const layer of state.activeLayers) {
    const option = document.createElement("option");
    option.value = layer.id;
    option.textContent = layerDisplayLabel(layer);
    elements.focusLayerSelect.append(option);
  }

  if (layerById(state.focusedLayerId)) {
    elements.focusLayerSelect.value = state.focusedLayerId;
  }
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

function setControlPane(paneKey) {
  state.controlPane = paneKey === "advanced" ? "advanced" : "simple";
  const isSimple = state.controlPane === "simple";

  elements.simplePane.hidden = !isSimple;
  elements.advancedPane.hidden = isSimple;
  elements.simplePane.classList.toggle("is-active", isSimple);
  elements.advancedPane.classList.toggle("is-active", !isSimple);
  elements.simplePaneButton.classList.toggle("is-active", isSimple);
  elements.advancedPaneButton.classList.toggle("is-active", !isSimple);
  elements.simplePaneButton.setAttribute("aria-pressed", String(isSimple));
  elements.advancedPaneButton.setAttribute("aria-pressed", String(!isSimple));
}

function manifestEntryByKey(datasetKey) {
  return state.manifest.find((dataset) => dataset.key === datasetKey) ?? null;
}

function manifestLabel(datasetKey) {
  return manifestEntryByKey(datasetKey)?.label ?? datasetKey;
}

function datasetForLayer(layer) {
  return state.datasetCache.get(layer.datasetKey) ?? null;
}

function focusedLayer() {
  return layerById(state.focusedLayerId);
}

function layerById(layerId) {
  return state.activeLayers.find((layer) => layer.id === layerId) ?? null;
}

function resolveMetricKey(dataset, metricKey) {
  if (
    metricKey &&
    dataset?.metadata.metrics.some((metric) => metric.key === metricKey)
  ) {
    return metricKey;
  }

  return preferredMetricKey(dataset);
}

function preferredMetricKey(dataset) {
  const preferred = dataset?.metadata.default_metric_key;
  if (
    preferred &&
    dataset.metadata.metrics.some((metric) => metric.key === preferred) &&
    dataset.records.some((record) => Number.isFinite(getMetricValue(record, preferred)))
  ) {
    return preferred;
  }
  return dataset?.metadata.metrics[0]?.key ?? "";
}

function renderOrder() {
  const focusedId = state.focusedLayerId;
  return [...state.activeLayers].sort((left, right) => {
    if (left.id === focusedId) {
      return 1;
    }
    if (right.id === focusedId) {
      return -1;
    }
    return 0;
  });
}

function collectVisibleRecords() {
  return state.activeLayers.flatMap((layer) => layer.filteredRecords);
}

function ensureFocusedLayerExists() {
  if (!layerById(state.focusedLayerId)) {
    state.focusedLayerId = state.activeLayers[0]?.id ?? "";
  }
}

function pruneSelectedRecords() {
  if (!findRecordByKey(state.activeRecordKey)) {
    state.activeRecordKey = "";
  }
  if (!findRecordByKey(state.hoverRecordKey)) {
    state.hoverRecordKey = "";
  }
}

function detailTarget() {
  return findRecordByKey(state.hoverRecordKey) ?? findRecordByKey(state.activeRecordKey);
}

function findRecordByKey(recordKey) {
  if (!recordKey) {
    return null;
  }

  const [layerId, recordId] = String(recordKey).split("::");
  const layer = layerById(layerId);
  if (!layer) {
    return null;
  }

  const record = layer.filteredRecords.find((entry) => entry.id === recordId);
  if (!record) {
    return null;
  }

  return { layer, record, recordKey };
}

function clearLayerRecordSelection(layerId) {
  if (recordKeyBelongsToLayer(state.activeRecordKey, layerId)) {
    state.activeRecordKey = "";
  }
  if (recordKeyBelongsToLayer(state.hoverRecordKey, layerId)) {
    state.hoverRecordKey = "";
  }
}

function clearAllRecordSelection() {
  state.activeRecordKey = "";
  state.hoverRecordKey = "";
}

function recordKeyBelongsToLayer(recordKey, layerId) {
  return String(recordKey || "").startsWith(`${layerId}::`);
}

function toRecordKey(layerId, recordId) {
  return `${layerId}::${recordId}`;
}

function disposeLayer(layer) {
  if (layer.heatLayer) {
    state.map.removeLayer(layer.heatLayer);
    layer.heatLayer = null;
  }
  if (layer.pointLayer) {
    layer.pointLayer.clearLayers();
    state.map.removeLayer(layer.pointLayer);
  }
}

function getMetricValue(record, metricKey) {
  return toNumber(record.metrics?.[metricKey]);
}

function displayMetricValue(record, metricKey) {
  const value = getMetricValue(record, metricKey);
  return Number.isFinite(value) ? formatMetric(value) : "No data";
}

function metricLabel(metricKey, layer) {
  const dataset =
    typeof layer === "string"
      ? state.datasetCache.get(layer) ?? null
      : datasetForLayer(layer);
  return dataset?.metadata.metrics.find((metric) => metric.key === metricKey)?.label ?? metricKey;
}

function layerDisplayLabel(layer) {
  return `${manifestLabel(layer.datasetKey)} - ${metricLabel(layer.metricKey, layer)}`;
}

function buildLayerFilterSummary(layer) {
  const parts = [];
  if (layer.stateFilter) {
    parts.push(`State: ${layer.stateFilter}`);
  }
  if (layer.groupFilter) {
    parts.push(`Group: ${layer.groupFilter}`);
  }
  if (parseInputNumber(layer.minimumValue) !== null) {
    parts.push(`Min: ${layer.minimumValue}`);
  }
  if (stringValue(layer.searchTerm)) {
    parts.push(`Search: ${stringValue(layer.searchTerm)}`);
  }
  return parts.join(" | ") || "No advanced filters applied";
}

function viewLabel(value) {
  if (value === "heat") {
    return "Heatmap only";
  }
  if (value === "points") {
    return "Points only";
  }
  return "Heatmap + points";
}

function markerRadius(value, maxValue, isHighlighted = false) {
  const layerAdjustment = state.activeLayers.length > 3 ? -0.45 : 0;
  const baseRadius =
    !Number.isFinite(value) || maxValue <= 0
      ? 3.2
      : 3.8 + Math.sqrt(value / maxValue) * 7.4 + layerAdjustment;
  return isHighlighted ? baseRadius + 1.3 : Math.max(2.8, baseRadius);
}

function markerColor(layer, value, maxValue) {
  if (!Number.isFinite(value) || maxValue <= 0) {
    return interpolateColor("#f5ece3", layer.color, 0.42);
  }

  const ratio = Math.max(0.18, Math.min(1, Math.sqrt(value / maxValue)));
  return interpolateColor("#fff5d6", layer.color, ratio);
}

function buildHeatGradient(baseHex) {
  return {
    0.2: interpolateColor("#fff5d6", baseHex, 0.3),
    0.55: interpolateColor("#fff5d6", baseHex, 0.68),
    0.9: adjustHexColor(baseHex, -0.24),
  };
}

function buildHoverSummaryHtml(layer, record) {
  return [
    `<div class="popup-title">${escapeHtml(record.title)}</div>`,
    record.subtitle ? `<div class="popup-line">${escapeHtml(record.subtitle)}</div>` : "",
    `<div class="popup-line">${escapeHtml(layerDisplayLabel(layer))}</div>`,
    `<div class="popup-line">${escapeHtml(metricLabel(layer.metricKey, layer))}: ${escapeHtml(displayMetricValue(record, layer.metricKey))}</div>`,
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

function emptyMetricStats() {
  return {
    values: [],
    countWithMetric: 0,
    positiveCount: 0,
    total: 0,
    maxValue: null,
    maxRecord: null,
  };
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

function adjustHexColor(hex, amount) {
  const rgb = hexToRgb(hex);
  const adjust = (value) => Math.max(0, Math.min(255, Math.round(value * (1 + amount))));
  return `rgb(${adjust(rgb.r)}, ${adjust(rgb.g)}, ${adjust(rgb.b)})`;
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
