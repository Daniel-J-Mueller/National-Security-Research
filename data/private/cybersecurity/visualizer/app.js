const API_VIEW = "/api/view";
const API_MANIFEST = "/api/manifest";
const API_EXPORT = "/api/export";
const API_OPTIONS = "/api/options";
const API_ROWS = "/api/rows";
const ANY_VALUE = "__RUNBOOK_ANY__";
const MAP_HEIGHT_STORAGE_KEY = "runbook-flow-visualizer-map-height";
const REFINED_MAP_HEIGHT_STORAGE_KEY = "runbook-flow-visualizer-refined-map-height";
const MAP_MIN_HEIGHT = 280;
const MAP_MAX_HEIGHT = 1200;
const OPTION_PAGE_SIZE = 120;
const ROW_PAGE_SIZE = 250;
const SCROLL_THRESHOLD = 100;

const numberFormatter = new Intl.NumberFormat("en-US");

const state = {
  manifest: null,
  view: null,
  filters: {},
  geoSelection: null,
  map: null,
  markerLayer: null,
  refinedMap: null,
  refinedMarkerLayer: null,
  selectedMapKey: "",
  selectedMapPoint: null,
  currentMapBounds: [],
  refinedMapBounds: [],
  mapResizeStartY: 0,
  mapResizeStartHeight: 0,
  mapResizeElement: null,
  mapResizeHandle: null,
  mapResizeStorageKey: "",
  mapResizeLeafletMap: null,
  columnSearches: {},
  columnPaging: {},
  resultSearch: "",
  resultPaging: {
    offset: 0,
    total: 0,
    hasMore: false,
    loading: false,
  },
};

const elements = {
  status: document.getElementById("status"),
  sourceFormat: document.getElementById("source-format"),
  shardCount: document.getElementById("shard-count"),
  totalRows: document.getElementById("total-rows"),
  matchingRows: document.getElementById("matching-rows"),
  outputDir: document.getElementById("output-dir"),
  map: document.getElementById("map"),
  refinedMap: document.getElementById("refined-map"),
  mapSummary: document.getElementById("map-summary"),
  refinedMapSummary: document.getElementById("refined-map-summary"),
  mapDetail: document.getElementById("map-detail"),
  mapResizeHandle: document.getElementById("map-resize-handle"),
  refinedMapResizeHandle: document.getElementById("refined-map-resize-handle"),
  zoomMapButton: document.getElementById("zoom-map-button"),
  zoomRefinedMapButton: document.getElementById("zoom-refined-map-button"),
  clearMapFilterButton: document.getElementById("clear-map-filter-button"),
  wizardColumns: document.getElementById("wizard-columns"),
  resultsHead: document.getElementById("results-head"),
  resultsBody: document.getElementById("results-body"),
  tableWrap: document.getElementById("table-wrap"),
  resultsSearch: document.getElementById("results-search"),
  previewNote: document.getElementById("preview-note"),
  clearButton: document.getElementById("clear-button"),
  refreshButton: document.getElementById("refresh-button"),
  exportRowsButton: document.getElementById("export-rows-button"),
  exportMappedButton: document.getElementById("export-mapped-button"),
};

document.addEventListener("DOMContentLoaded", () => {
  bindEvents();
  applyStoredMapHeight();
  buildMaps();
  void loadAll();
});

function bindEvents() {
  elements.clearButton.addEventListener("click", () => {
    state.filters = {};
    state.geoSelection = null;
    state.selectedMapKey = "";
    state.selectedMapPoint = null;
    state.columnSearches = {};
    state.resultSearch = "";
    elements.resultsSearch.value = "";
    void loadView();
  });

  elements.refreshButton.addEventListener("click", () => {
    void loadAll();
  });

  elements.exportRowsButton.addEventListener("click", () => {
    void exportRows();
  });

  elements.exportMappedButton.addEventListener("click", () => {
    void exportMappedIps();
  });

  elements.zoomMapButton.addEventListener("click", () => {
    zoomMapToBounds(state.map, state.currentMapBounds);
  });

  elements.zoomRefinedMapButton.addEventListener("click", () => {
    zoomMapToBounds(state.refinedMap, state.refinedMapBounds);
  });

  elements.clearMapFilterButton.addEventListener("click", () => {
    clearMapSelection();
  });

  elements.resultsSearch.addEventListener(
    "input",
    debounce(() => {
      state.resultSearch = elements.resultsSearch.value;
      renderResults();
    }, 180),
  );

  elements.tableWrap.addEventListener("scroll", () => {
    maybeLoadMoreRows();
  });

  if (elements.mapResizeHandle) {
    elements.mapResizeHandle.addEventListener("pointerdown", (event) => {
      startMapResize(event, elements.map, elements.mapResizeHandle, state.map, MAP_HEIGHT_STORAGE_KEY);
    });
    elements.mapResizeHandle.addEventListener("dblclick", () => {
      setMapHeight(elements.map, state.map, defaultMapHeight(), true, MAP_HEIGHT_STORAGE_KEY);
    });
  }

  if (elements.refinedMapResizeHandle) {
    elements.refinedMapResizeHandle.addEventListener("pointerdown", (event) => {
      startMapResize(
        event,
        elements.refinedMap,
        elements.refinedMapResizeHandle,
        state.refinedMap,
        REFINED_MAP_HEIGHT_STORAGE_KEY,
      );
    });
    elements.refinedMapResizeHandle.addEventListener("dblclick", () => {
      setMapHeight(
        elements.refinedMap,
        state.refinedMap,
        defaultRefinedMapHeight(),
        true,
        REFINED_MAP_HEIGHT_STORAGE_KEY,
      );
    });
  }
}

async function loadAll() {
  setStatus("Loading runbook shard metadata...");
  try {
    state.manifest = await fetchJson(API_MANIFEST);
    renderMetrics();
    await loadView();
  } catch (error) {
    setStatus(`Could not load visualizer data: ${error.message}`);
  }
}

async function loadView() {
  const params = viewParams();
  const url = `${API_VIEW}?${params.toString()}`;
  setStatus("Updating flow columns...");
  try {
    state.view = await fetchJson(url);
    state.filters = { ...state.view.filters };
    state.geoSelection = normalizeGeoSelection(state.view.geo_filter, state.geoSelection);
    state.selectedMapKey = state.geoSelection ? state.geoSelection.key : "";
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
  renderMapControls();
  renderTopMap();
  renderWizard();
  renderResults();
  renderRefinedMap();
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

function renderMapControls() {
  const hasGeoSelection = Boolean(state.geoSelection);
  elements.clearMapFilterButton.disabled = !hasGeoSelection;
}

function buildMaps() {
  if (!window.L) {
    elements.mapSummary.textContent = "Map library unavailable.";
    elements.refinedMapSummary.textContent = "Map library unavailable.";
    return;
  }

  state.map = createMap(elements.map).setView([39.5, -98.35], 1);
  state.markerLayer = L.layerGroup().addTo(state.map);

  state.refinedMap = createMap(elements.refinedMap).setView([39.5, -98.35], 1);
  state.refinedMarkerLayer = L.layerGroup().addTo(state.refinedMap);
}

function createMap(element) {
  const map = L.map(element, {
    preferCanvas: true,
    worldCopyJump: true,
  });

  L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
    attribution: "&copy; OpenStreetMap contributors &copy; CARTO",
    maxZoom: 19,
  }).addTo(map);

  window.setTimeout(() => map.invalidateSize(), 0);
  return map;
}

function defaultMapHeight() {
  const lower = window.innerWidth <= 860 ? 300 : 420;
  const upper = window.innerWidth <= 860 ? 560 : 700;
  return clampNumber(Math.round(window.innerHeight * 0.56), lower, upper);
}

function defaultRefinedMapHeight() {
  return defaultMapHeight();
}

function applyStoredMapHeight() {
  const stored = Number(window.localStorage.getItem(MAP_HEIGHT_STORAGE_KEY));
  setMapHeight(
    elements.map,
    state.map,
    Number.isFinite(stored) && stored > 0 ? stored : defaultMapHeight(),
    false,
    MAP_HEIGHT_STORAGE_KEY,
  );

  const refinedStored = Number(window.localStorage.getItem(REFINED_MAP_HEIGHT_STORAGE_KEY));
  setMapHeight(
    elements.refinedMap,
    state.refinedMap,
    Number.isFinite(refinedStored) && refinedStored > 0 ? refinedStored : defaultRefinedMapHeight(),
    false,
    REFINED_MAP_HEIGHT_STORAGE_KEY,
  );
}

function setMapHeight(mapElement, leafletMap, height, persist, storageKey) {
  if (!mapElement) {
    return;
  }
  const clamped = clampNumber(Math.round(height), MAP_MIN_HEIGHT, MAP_MAX_HEIGHT);
  mapElement.style.setProperty("--map-height", `${clamped}px`);
  if (persist && storageKey) {
    window.localStorage.setItem(storageKey, String(clamped));
  }
  if (mapElement === elements.map || mapElement === elements.refinedMap) {
    invalidateMapPairSizes();
  } else if (leafletMap) {
    window.requestAnimationFrame(() => leafletMap.invalidateSize());
  }
}

function invalidateMapPairSizes() {
  window.requestAnimationFrame(() => {
    if (state.map) {
      state.map.invalidateSize();
    }
    if (state.refinedMap) {
      state.refinedMap.invalidateSize();
    }
  });
}

function startMapResize(event, mapElement, handle, leafletMap, storageKey) {
  if (!mapElement || !handle) {
    return;
  }
  event.preventDefault();
  state.mapResizeStartY = event.clientY;
  state.mapResizeStartHeight = mapElement.getBoundingClientRect().height;
  state.mapResizeElement = mapElement;
  state.mapResizeHandle = handle;
  state.mapResizeLeafletMap = leafletMap;
  state.mapResizeStorageKey = storageKey;
  handle.setPointerCapture(event.pointerId);
  handle.addEventListener("pointermove", resizeMap);
  handle.addEventListener("pointerup", stopMapResize);
  handle.addEventListener("pointercancel", stopMapResize);
}

function resizeMap(event) {
  const nextHeight = state.mapResizeStartHeight + event.clientY - state.mapResizeStartY;
  setMapHeight(state.mapResizeElement, state.mapResizeLeafletMap, nextHeight, false, state.mapResizeStorageKey);
}

function stopMapResize(event) {
  const handle = state.mapResizeHandle;
  const mapElement = state.mapResizeElement;
  if (!handle || !mapElement) {
    return;
  }
  if (handle.hasPointerCapture(event.pointerId)) {
    handle.releasePointerCapture(event.pointerId);
  }
  handle.removeEventListener("pointermove", resizeMap);
  handle.removeEventListener("pointerup", stopMapResize);
  handle.removeEventListener("pointercancel", stopMapResize);
  setMapHeight(
    mapElement,
    state.mapResizeLeafletMap,
    mapElement.getBoundingClientRect().height,
    true,
    state.mapResizeStorageKey,
  );
  state.mapResizeElement = null;
  state.mapResizeHandle = null;
  state.mapResizeLeafletMap = null;
  state.mapResizeStorageKey = "";
}

function renderTopMap() {
  const view = state.view || {};
  const points = Array.isArray(view.map_points) ? view.map_points : [];
  const totalPoints = view.map_point_count || points.length;

  if (!state.map || !state.markerLayer) {
    elements.mapSummary.textContent = `${numberFormatter.format(totalPoints)} mapped IPs.`;
    return;
  }

  state.markerLayer.clearLayers();
  elements.mapSummary.textContent = buildMapSummary(view, totalPoints);

  const validPoints = validMapPoints(points);
  if (!validPoints.length) {
    state.map.setView([20, 0], 2);
    state.currentMapBounds = [];
    state.selectedMapPoint = null;
    renderMapDetail(null);
    return;
  }

  const bounds = [];
  let selectedPoint = null;
  validPoints.forEach((point) => {
    const selected = Boolean(state.geoSelection && state.geoSelection.key === point.key);
    const marker = buildPointMarker(point, selected ? "selected" : "top");
    marker.bindPopup(buildMapPopup(point), { maxWidth: 340 });
    marker.on("click", () => {
      selectMapRegion(point);
      marker.openPopup();
    });
    marker.addTo(state.markerLayer);
    bounds.push([point.latNumber, point.longNumber]);
    if (selected) {
      selectedPoint = point;
    }
  });

  state.currentMapBounds = bounds;
  state.selectedMapPoint = selectedPoint;
  renderMapDetail(selectedPoint);
  zoomMapToBounds(state.map, state.currentMapBounds);
}

function renderRefinedMap() {
  if (!state.refinedMap || !state.refinedMarkerLayer) {
    elements.refinedMapSummary.textContent = "Selection map unavailable.";
    return;
  }

  state.refinedMarkerLayer.clearLayers();

  const point = selectedExpandedPoint();
  if (!point) {
    state.refinedMap.setView([20, 0], 2);
    state.refinedMapBounds = [];
    elements.refinedMapSummary.textContent = "Choose a coordinate on the left.";
    return;
  }

  const serverDots = expandedServerDots(point);
  const bounds = [[point.latNumber, point.longNumber]];
  serverDots.forEach((dot) => {
    const marker = buildExpandedServerMarker(dot);
    marker.bindPopup(buildExpandedServerPopup(dot, point), { maxWidth: 340 });
    marker.addTo(state.refinedMarkerLayer);
    bounds.push([dot.lat, dot.long]);
  });

  state.refinedMapBounds = bounds;
  elements.refinedMapSummary.textContent = buildExpandedMapSummary(point, serverDots);
  renderMapDetail(point);
  zoomMapToBounds(state.refinedMap, state.refinedMapBounds);
}

function validMapPoints(points) {
  return points
    .map((point) => ({
      ...point,
      latNumber: Number(point.lat),
      longNumber: Number(point.long),
    }))
    .filter((point) => Number.isFinite(point.latNumber) && Number.isFinite(point.longNumber));
}

function buildPointMarker(point, mode) {
  const ipCount = Number(point.ip_count || 1);
  const styles = {
    top: { color: "#0f4b51", fillColor: "#176b73" },
    selected: { color: "#7a2f12", fillColor: "#d47f2f" },
    refined: { color: "#254f78", fillColor: "#3d75a3" },
  };
  const style = styles[mode] || styles.top;

  return L.circleMarker([point.latNumber, point.longNumber], {
    radius: Math.min(18, 6 + Math.sqrt(ipCount)),
    weight: 2,
    color: style.color,
    fillColor: style.fillColor,
    fillOpacity: 0.8,
  });
}

function selectedExpandedPoint() {
  if (!state.geoSelection) {
    return null;
  }
  const view = state.view || {};
  const candidates = [];
  if (Array.isArray(view.refined_map_points)) {
    candidates.push(...view.refined_map_points);
  }
  if (state.selectedMapPoint) {
    candidates.push(state.selectedMapPoint);
  }
  if (Array.isArray(view.map_points)) {
    candidates.push(...view.map_points);
  }

  const validPoints = validMapPoints(candidates);
  return (
    validPoints.find((point) => point.key && point.key === state.geoSelection.key) ||
    validPoints[0] ||
    null
  );
}

function expandedServerDots(point) {
  const records = Array.isArray(point.cache_records) ? point.cache_records : [];
  const total = Math.max(records.length, Number(point.ip_count || 0), 1);
  return records.map((record, index) => {
    const pingMs = parsePingMs(record.ping_rtt_ms);
    const seed = `${point.key || ""}:${record.ip || index}`;
    const bearing = stableUnit(`${seed}:bearing`) * Math.PI * 2;
    const radiusFactor = 0.35 + stableUnit(`${seed}:radius`) * 0.65;
    const distanceKm = pingDistanceKm(pingMs, total) * radiusFactor;
    const coordinate = destinationCoordinate(point.latNumber, point.longNumber, distanceKm, bearing);
    return {
      record,
      index,
      lat: coordinate.lat,
      long: coordinate.long,
      pingMs,
      distanceKm,
    };
  });
}

function buildExpandedServerMarker(dot) {
  const pingMs = dot.pingMs;
  const radius = Number.isFinite(pingMs) ? clampNumber(3.5 + Math.sqrt(pingMs) * 0.28, 4, 8) : 4.5;
  return L.circleMarker([dot.lat, dot.long], {
    radius,
    weight: 1,
    color: "#254f78",
    fillColor: "#3d75a3",
    fillOpacity: 0.78,
  });
}

function buildMapSummary(view, totalPoints) {
  const mappedIps = numberFormatter.format(view.mapped_ip_count || 0);
  const pointText = numberFormatter.format(totalPoints);
  const ok = numberFormatter.format(view.coordinate_lookup_ok_count || 0);
  const errors = numberFormatter.format(view.coordinate_lookup_error_count || 0);
  const geoText = state.geoSelection ? ` Region filter: ${state.geoSelection.label || state.geoSelection.key}.` : "";
  return `${pointText} map points, ${mappedIps} mapped IPs. Lookups: ${ok} ok, ${errors} not mapped.${geoText}`;
}

function buildRefinedMapSummary(view, totalPoints) {
  const mappedIps = numberFormatter.format(view.refined_mapped_ip_count || 0);
  if (!totalPoints) {
    return "No mapped IPs in the refined selection.";
  }
  return `${numberFormatter.format(totalPoints)} selection points, ${mappedIps} mapped IPs.`;
}

function buildExpandedMapSummary(point, dots) {
  const ipCount = dots.length || Number(point.ip_count || 0);
  if (!ipCount) {
    return "Selected coordinate has no cached server records.";
  }
  const pingValues = dots.map((dot) => dot.pingMs).filter((value) => Number.isFinite(value));
  if (!pingValues.length) {
    return `${numberFormatter.format(ipCount)} servers expanded near ${locationLabel(point) || point.key}.`;
  }
  const minPing = Math.min(...pingValues);
  const maxPing = Math.max(...pingValues);
  return `${numberFormatter.format(ipCount)} servers expanded near ${
    locationLabel(point) || point.key
  }. Ping spread ${formatMs(minPing)}-${formatMs(maxPing)}.`;
}

function zoomMapToBounds(map, bounds) {
  if (!map || !bounds.length) {
    return;
  }
  if (bounds.length === 1) {
    map.setView(bounds[0], Math.max(map.getZoom(), 7));
  } else {
    map.fitBounds(bounds, { padding: [24, 24] });
  }
}

function selectMapRegion(point) {
  const ips = Array.isArray(point.ips) ? point.ips.map(String).filter(Boolean) : [];
  state.geoSelection = {
    key: point.key,
    label: locationLabel(point) || point.key,
    ips,
  };
  state.selectedMapKey = point.key;
  state.selectedMapPoint = point;
  state.columnSearches = {};
  state.resultSearch = "";
  elements.resultsSearch.value = "";
  renderMapControls();
  renderMapDetail(point);
  renderRefinedMap();
  void loadView();
}

function clearMapSelection() {
  state.geoSelection = null;
  state.selectedMapKey = "";
  state.selectedMapPoint = null;
  state.columnSearches = {};
  state.resultSearch = "";
  elements.resultsSearch.value = "";
  renderMapControls();
  void loadView();
}

function buildMapPopup(point) {
  const ipCount = Number(point.ip_count || 0);
  const ports = Array.isArray(point.ports) ? point.ports.slice(0, 12).join(", ") : "";
  const rows = [
    ["IPs", numberFormatter.format(ipCount)],
    ["Location", locationLabel(point)],
    ["Long", point.long_text || point.long || ""],
    ["Lat", point.lat_text || point.lat || ""],
    ["Rows", numberFormatter.format(point.row_count || 0)],
    ["Open services", numberFormatter.format(point.open_service_count || 0)],
    ["Ports", ports],
  ]
    .filter(([_label, value]) => String(value || "").trim())
    .map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd>`)
    .join("");

  return `<div class="map-popup"><h3>${escapeHtml(locationLabel(point) || "Mapped coordinate")}</h3><dl>${rows}</dl></div>`;
}

function buildExpandedServerPopup(dot, point) {
  const record = dot.record || {};
  const rows = [
    ["IP", record.ip],
    ["Location", locationLabel(point)],
    ["Ping", Number.isFinite(dot.pingMs) ? formatMs(dot.pingMs) : record.ping_status],
    ["Offset", `${dot.distanceKm.toFixed(1)} km`],
    ["Provider", record.coordinate_provider],
    ["Org", record.org],
    ["ASN", record.asn],
    ["Looked up", record.looked_up_at],
  ]
    .filter(([_label, value]) => String(value || "").trim())
    .map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd>`)
    .join("");

  return `<div class="map-popup"><h3>${escapeHtml(record.ip || "Server")}</h3><dl>${rows}</dl></div>`;
}

function renderMapDetail(point) {
  if (!elements.mapDetail) {
    return;
  }
  elements.mapDetail.textContent = "";
  if (!point) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "Select a map point to refine the flow wizard by coordinate.";
    elements.mapDetail.appendChild(empty);
    return;
  }

  const header = document.createElement("div");
  header.className = "map-detail-header";
  const title = document.createElement("h3");
  title.textContent = locationLabel(point) || "Mapped coordinate";
  const meta = document.createElement("p");
  meta.className = "note";
  meta.textContent = `${numberFormatter.format(point.ip_count || 0)} IPs at ${point.long_text || point.long}, ${
    point.lat_text || point.lat
  }`;
  header.append(title, meta);

  const table = document.createElement("table");
  table.className = "map-detail-table";
  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  ["IP", "Provider", "Ping", "Org", "ASN", "Looked Up"].forEach((label) => {
    const th = document.createElement("th");
    th.textContent = label;
    headRow.appendChild(th);
  });
  thead.appendChild(headRow);

  const tbody = document.createElement("tbody");
  const records = Array.isArray(point.cache_records) ? point.cache_records : [];
  records.forEach((record) => {
    const row = document.createElement("tr");
    [
      record.ip,
      record.coordinate_provider,
      record.ping_status,
      record.org,
      record.asn,
      record.looked_up_at,
    ].forEach((value) => {
      const td = document.createElement("td");
      td.textContent = displayValue(value || "");
      row.appendChild(td);
    });
    tbody.appendChild(row);
  });
  table.append(thead, tbody);

  const tableWrap = document.createElement("div");
  tableWrap.className = "map-detail-table-wrap";
  tableWrap.appendChild(table);

  elements.mapDetail.append(header, tableWrap);
}

function locationLabel(point) {
  return [point.city, point.region, point.country].filter(Boolean).join(", ");
}

function renderWizard() {
  const view = state.view;
  elements.wizardColumns.textContent = "";
  state.columnPaging = {};

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
  const selectedText = hasSelectedValue ? `, selected ${displayValue(selectedValue)}` : "";
  detail.textContent = `${numberFormatter.format(column.unsearched_total_options || column.total_options || 0)} values from ${numberFormatter.format(
    column.matched_rows || 0,
  )} rows${selectedText}`;
  header.append(title, detail);

  const selectWrap = document.createElement("div");
  selectWrap.className = "column-select";
  const actions = document.createElement("div");
  actions.className = "column-filter-actions";
  const searchLabel = document.createElement("label");
  searchLabel.className = "search-label";
  const searchText = document.createElement("span");
  searchText.textContent = "Search values";
  const searchInput = document.createElement("input");
  searchInput.className = "list-search";
  searchInput.type = "search";
  searchInput.autocomplete = "off";
  searchInput.value = state.columnSearches[field] || "";
  searchInput.setAttribute("aria-label", `Search ${labelFor(field)} values`);
  searchInput.addEventListener(
    "input",
    debounce(() => {
      state.columnSearches[field] = searchInput.value;
      resetColumnPage(field);
    }, 180),
  );
  searchLabel.append(searchText, searchInput);

  const clearValueButton = document.createElement("button");
  clearValueButton.type = "button";
  clearValueButton.className = "button secondary small";
  clearValueButton.textContent = "Any";
  clearValueButton.disabled = !hasSelectedValue;
  clearValueButton.addEventListener("click", () => {
    setFilter(field, ANY_VALUE, index);
  });
  actions.append(searchLabel, clearValueButton);
  selectWrap.appendChild(actions);

  const list = document.createElement("div");
  list.className = "option-list";
  list.addEventListener("scroll", () => {
    maybeLoadMoreOptions(field);
  });

  const footer = document.createElement("div");
  footer.className = "column-footer";

  const page = {
    field,
    index,
    list,
    footer,
    search: state.columnSearches[field] || "",
    offset: 0,
    total: 0,
    hasMore: false,
    loading: false,
  };
  state.columnPaging[field] = page;

  if (page.search) {
    setListMessage(list, "Searching values...");
    renderColumnFooter(page);
    void loadColumnOptions(field, true);
  } else {
    applyColumnPayload(page, column, true);
  }

  wrapper.append(header, selectWrap, list, footer);
  return wrapper;
}

function applyColumnPayload(page, payload, reset) {
  if (reset) {
    page.list.textContent = "";
  }
  const options = Array.isArray(payload.options) ? payload.options : [];
  page.offset = Number(payload.offset || 0);
  page.total = Number(payload.total_options || 0);
  page.hasMore = Boolean(payload.has_more);
  appendColumnOptions(page, options);
  page.offset += options.length;
  if (!page.offset && !options.length) {
    setListMessage(page.list, page.search ? "No values match this search." : "No values match the current path.");
  }
  renderColumnFooter(page);
}

function appendColumnOptions(page, options) {
  options.forEach((option) => {
    const button = document.createElement("button");
    button.type = "button";
    const isActive = Object.prototype.hasOwnProperty.call(state.filters, page.field) && option.value === state.filters[page.field];
    button.className = isActive ? "option-button is-active" : "option-button";
    button.title = displayValue(option.value);
    button.addEventListener("click", () => {
      setFilter(page.field, option.value, page.index);
    });

    const value = document.createElement("span");
    value.className = option.value ? "option-value" : "option-value blank";
    value.textContent = displayValue(option.value);

    const count = document.createElement("span");
    count.className = "option-count";
    count.textContent = numberFormatter.format(option.count);

    button.append(value, count);
    page.list.appendChild(button);
  });
}

function renderColumnFooter(page) {
  page.footer.textContent = "";

  const exportButton = document.createElement("button");
  exportButton.type = "button";
  exportButton.className = "button small";
  exportButton.textContent = "Export column CSV";
  exportButton.addEventListener("click", () => {
    void exportColumn(page.field);
  });
  page.footer.appendChild(exportButton);

  const status = document.createElement("p");
  status.className = "column-status";
  if (page.loading) {
    status.textContent = "Loading more values...";
  } else if (!page.total) {
    status.textContent = "No values to show.";
  } else if (page.hasMore) {
    status.textContent = `Showing ${numberFormatter.format(page.offset)} of ${numberFormatter.format(page.total)} values. Scroll for more.`;
  } else {
    status.textContent = `Showing all ${numberFormatter.format(page.total)} values.`;
  }
  page.footer.appendChild(status);
}

function resetColumnPage(field) {
  const page = state.columnPaging[field];
  if (!page) {
    return;
  }
  page.search = state.columnSearches[field] || "";
  page.offset = 0;
  page.total = 0;
  page.hasMore = true;
  page.loading = false;
  setListMessage(page.list, page.search ? "Searching values..." : "Loading values...");
  renderColumnFooter(page);
  void loadColumnOptions(field, true);
}

async function loadColumnOptions(field, reset = false) {
  const page = state.columnPaging[field];
  if (!page || page.loading || (!reset && !page.hasMore)) {
    return;
  }

  page.loading = true;
  renderColumnFooter(page);

  const params = viewParams();
  params.set("field", field);
  params.set("search", page.search);
  params.set("offset", reset ? "0" : String(page.offset));
  params.set("limit", String(OPTION_PAGE_SIZE));

  try {
    const payload = await fetchJson(`${API_OPTIONS}?${params.toString()}`);
    applyColumnPayload(page, payload, reset);
  } catch (error) {
    setListMessage(page.list, `Could not load values: ${error.message}`);
    page.hasMore = false;
    renderColumnFooter(page);
  } finally {
    page.loading = false;
    renderColumnFooter(page);
  }
}

function maybeLoadMoreOptions(field) {
  const page = state.columnPaging[field];
  if (!page || page.loading || !page.hasMore) {
    return;
  }
  if (page.list.scrollTop + page.list.clientHeight >= page.list.scrollHeight - SCROLL_THRESHOLD) {
    void loadColumnOptions(field, false);
  }
}

function renderResults() {
  const view = state.view;
  elements.resultsHead.textContent = "";
  elements.resultsBody.textContent = "";

  if (!view || !Array.isArray(view.headers) || !view.headers.length) {
    elements.previewNote.textContent = "";
    return;
  }

  elements.resultsSearch.value = state.resultSearch;

  const headerRow = document.createElement("tr");
  view.headers.forEach((header) => {
    const th = document.createElement("th");
    th.textContent = labelFor(header);
    headerRow.appendChild(th);
  });
  elements.resultsHead.appendChild(headerRow);

  state.resultPaging = {
    offset: 0,
    total: 0,
    hasMore: false,
    loading: false,
  };

  if (state.resultSearch.trim()) {
    showRowsMessage("Searching rows...");
    state.resultPaging.hasMore = true;
    updateResultsNote();
    void loadRows(true);
    return;
  }

  const rows = Array.isArray(view.rows) ? view.rows : [];
  appendRows(rows, true);
  state.resultPaging.offset = rows.length;
  state.resultPaging.total = Number(view.matching_count || 0);
  state.resultPaging.hasMore = Boolean(view.rows_has_more) || rows.length < state.resultPaging.total;

  if (!rows.length) {
    showRowsMessage("No rows match the current path.");
  }
  updateResultsNote();
}

async function loadRows(reset = false) {
  const view = state.view;
  if (!view || state.resultPaging.loading || (!reset && !state.resultPaging.hasMore)) {
    return;
  }

  state.resultPaging.loading = true;
  updateResultsNote();

  const params = viewParams();
  params.set("search", state.resultSearch);
  params.set("offset", reset ? "0" : String(state.resultPaging.offset));
  params.set("limit", String(ROW_PAGE_SIZE));

  try {
    const payload = await fetchJson(`${API_ROWS}?${params.toString()}`);
    const rows = Array.isArray(payload.rows) ? payload.rows : [];
    if (reset) {
      elements.resultsBody.textContent = "";
    }
    appendRows(rows, reset);
    state.resultPaging.offset = Number(payload.offset || 0) + rows.length;
    state.resultPaging.total = Number(payload.total_rows || 0);
    state.resultPaging.hasMore = Boolean(payload.has_more);
    if (!state.resultPaging.offset && !rows.length) {
      showRowsMessage(state.resultSearch.trim() ? "No rows match this search." : "No rows match the current path.");
    }
  } catch (error) {
    showRowsMessage(`Could not load rows: ${error.message}`);
    state.resultPaging.hasMore = false;
  } finally {
    state.resultPaging.loading = false;
    updateResultsNote();
  }
}

function appendRows(rows) {
  const view = state.view;
  rows.forEach((row) => {
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
}

function maybeLoadMoreRows() {
  if (state.resultPaging.loading || !state.resultPaging.hasMore) {
    return;
  }
  if (elements.tableWrap.scrollTop + elements.tableWrap.clientHeight >= elements.tableWrap.scrollHeight - SCROLL_THRESHOLD) {
    void loadRows(false);
  }
}

function showRowsMessage(message) {
  const view = state.view;
  const tr = document.createElement("tr");
  const td = document.createElement("td");
  td.className = "empty-state";
  td.colSpan = view && Array.isArray(view.headers) ? view.headers.length : 1;
  td.textContent = message;
  tr.appendChild(td);
  elements.resultsBody.textContent = "";
  elements.resultsBody.appendChild(tr);
}

function updateResultsNote() {
  const visible = state.resultPaging.offset;
  const total = state.resultPaging.total;
  const searchText = state.resultSearch.trim() ? " search" : "";
  if (state.resultPaging.loading) {
    elements.previewNote.textContent = "Loading rows...";
  } else if (state.resultPaging.hasMore) {
    elements.previewNote.textContent = `Showing ${numberFormatter.format(visible)} of ${numberFormatter.format(total)}${searchText} rows. Scroll for more.`;
  } else {
    elements.previewNote.textContent = `${numberFormatter.format(total)}${searchText} rows.`;
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
  state.columnSearches = {};
  state.resultSearch = "";
  elements.resultsSearch.value = "";
  void loadView();
}

async function exportColumn(field) {
  setStatus(`Writing ${labelFor(field)} column CSV...`);
  try {
    const payload = await fetchJson(API_EXPORT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ field, filters: state.filters, geo_filter: geoFilterPayload() }),
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
      body: JSON.stringify({ type: "rows", filters: state.filters, geo_filter: geoFilterPayload() }),
    });
    setStatus(`Wrote ${numberFormatter.format(payload.rows_written)} rows to ${payload.path}.`);
  } catch (error) {
    setStatus(`Export failed: ${error.message}`);
  }
}

async function exportMappedIps() {
  setStatus("Writing mapped IP CSV...");
  try {
    const payload = await fetchJson(API_EXPORT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type: "mapped-ips", filters: state.filters, geo_filter: geoFilterPayload() }),
    });
    setStatus(`Wrote ${numberFormatter.format(payload.rows_written)} mapped IP rows to ${payload.path}.`);
  } catch (error) {
    setStatus(`Mapped IP export failed: ${error.message}`);
  }
}

function viewParams() {
  const params = new URLSearchParams();
  params.set("filters", JSON.stringify(state.filters));
  params.set("geo_filter", JSON.stringify(geoFilterPayload()));
  return params;
}

function geoFilterPayload() {
  if (!state.geoSelection) {
    return {};
  }
  const ips = Array.isArray(state.geoSelection.ips) ? state.geoSelection.ips : [];
  return {
    key: state.geoSelection.key || "",
    label: state.geoSelection.label || "",
    ips: state.geoSelection.key && ips.length > 200 ? [] : ips,
  };
}

function normalizeGeoSelection(payload, previous) {
  if (!payload || typeof payload !== "object") {
    return null;
  }
  const ips = Array.isArray(payload.ips) ? payload.ips.map(String).filter(Boolean) : [];
  const key = String(payload.key || previous?.key || "");
  const label = String(payload.label || previous?.label || key);
  if (!key && !ips.length) {
    return null;
  }
  return { key, label, ips };
}

function setListMessage(list, message) {
  list.textContent = "";
  const empty = document.createElement("p");
  empty.className = "empty-state";
  empty.textContent = message;
  list.appendChild(empty);
}

function setStatus(message) {
  elements.status.textContent = message;
}

function displayValue(value) {
  return value === "" ? "(blank)" : String(value);
}

function escapeHtml(value) {
  const replacements = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  };
  return String(value ?? "").replace(/[&<>"']/g, (character) => replacements[character]);
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

function parsePingMs(value) {
  const text = String(value || "").trim();
  if (!text) {
    return NaN;
  }
  const parsed = Number(text.replace(/ms$/i, "").trim());
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : NaN;
}

function pingDistanceKm(pingMs, total) {
  // Scale by RTT without using the raw physical upper bound, which would push dots far outside the selected region.
  if (Number.isFinite(pingMs) && pingMs > 0) {
    return clampNumber(6 + Math.pow(Math.min(pingMs, 500), 0.82) * 3.4, 8, 420);
  }
  return clampNumber(12 + Math.sqrt(total) * 4, 12, 90);
}

function destinationCoordinate(lat, long, distanceKm, bearingRadians) {
  const earthRadiusKm = 6371;
  const angularDistance = distanceKm / earthRadiusKm;
  const lat1 = toRadians(lat);
  const lon1 = toRadians(long);
  const lat2 = Math.asin(
    Math.sin(lat1) * Math.cos(angularDistance) +
      Math.cos(lat1) * Math.sin(angularDistance) * Math.cos(bearingRadians),
  );
  const lon2 =
    lon1 +
    Math.atan2(
      Math.sin(bearingRadians) * Math.sin(angularDistance) * Math.cos(lat1),
      Math.cos(angularDistance) - Math.sin(lat1) * Math.sin(lat2),
    );
  return {
    lat: toDegrees(lat2),
    long: normalizeLongitude(toDegrees(lon2)),
  };
}

function stableUnit(seed) {
  return hashString(seed) / 0xffffffff;
}

function hashString(value) {
  let hash = 2166136261;
  const text = String(value || "");
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function formatMs(value) {
  return `${Number(value).toFixed(value < 10 ? 1 : 0)} ms`;
}

function toRadians(value) {
  return (value * Math.PI) / 180;
}

function toDegrees(value) {
  return (value * 180) / Math.PI;
}

function normalizeLongitude(value) {
  return ((((value + 180) % 360) + 360) % 360) - 180;
}

function clampNumber(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function debounce(callback, delay) {
  let timeoutId;
  return (...args) => {
    window.clearTimeout(timeoutId);
    timeoutId = window.setTimeout(() => callback(...args), delay);
  };
}
