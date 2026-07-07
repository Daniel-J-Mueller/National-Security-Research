const API_VIEW = "/api/view";
const API_MANIFEST = "/api/manifest";
const API_EXPORT = "/api/export";
const API_OPTIONS = "/api/options";
const API_ROWS = "/api/rows";
const API_MAP_CHUNKS = "/api/map-chunks";
const API_MAP_SELECTION = "/api/map-selection";
const API_REFRESH = "/api/refresh";
const ANY_VALUE = "__RUNBOOK_ANY__";
const MAP_HEIGHT_STORAGE_KEY = "dock-1-map-height-v2";
const REFINED_MAP_HEIGHT_STORAGE_KEY = "dock-1-refined-map-height-v2";
const MAP_MIN_HEIGHT = 320;
const MAP_MAX_HEIGHT = 1600;
const OPTION_PAGE_SIZE = 120;
const ROW_PAGE_SIZE = 250;
const SCROLL_THRESHOLD = 100;
const OPTION_RENDER_CHUNK_SIZE = 50;
const ROW_RENDER_CHUNK_SIZE = 50;
const MAP_MARKER_RENDER_CHUNK_SIZE = 250;
const PROGRESS_HIDE_DELAY = 450;

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
  mapChunkRequestId: 0,
  mapSelectionRequestId: 0,
  mapChunkLoadTimer: null,
  mapChunkInitialized: false,
  mapChunkPayload: null,
  viewRequestId: 0,
  progressHideTimer: null,
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
  progress: document.getElementById("load-progress"),
  progressBar: document.getElementById("load-progress-bar"),
  map: document.getElementById("map"),
  refinedMap: document.getElementById("refined-map"),
  mapSummary: document.getElementById("map-summary"),
  refinedMapSummary: document.getElementById("refined-map-summary"),
  mapDetail: document.getElementById("map-detail"),
  mapResizeHandle: document.getElementById("map-resize-handle"),
  refinedMapResizeHandle: document.getElementById("refined-map-resize-handle"),
  mapZoomSlider: document.getElementById("map-zoom-slider"),
  refinedMapZoomSlider: document.getElementById("refined-map-zoom-slider"),
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
  statsGrid: document.getElementById("stats-grid"),
  debugBody: document.getElementById("debug-body"),
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
    void loadAll({ force: true });
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
  window.addEventListener(
    "scroll",
    debounce(() => {
      maybeLoadVisibleColumnOptions();
      maybeLoadMoreRows();
    }, 120),
    { passive: true },
  );

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

async function loadAll(options = {}) {
  const force = Boolean(options.force);
  startTopProgress(force ? "Refreshing runbook..." : "Loading runbook...", { indeterminate: true });
  await nextFrame();
  try {
    if (force) {
      state.mapChunkRequestId += 1;
      state.mapSelectionRequestId += 1;
      state.mapChunkPayload = null;
      if (state.mapChunkLoadTimer) {
        clearTimeout(state.mapChunkLoadTimer);
        state.mapChunkLoadTimer = null;
      }
      const refreshPayload = await fetchJson(API_REFRESH, { method: "POST" });
      state.manifest = refreshPayload.manifest || (await fetchJson(API_MANIFEST));
    } else {
      state.manifest = await fetchJson(API_MANIFEST);
    }
    updateTopProgress(18, { indeterminate: false, message: "Loaded runbook metadata." });
    renderMetrics();
    await loadView();
  } catch (error) {
    stopTopProgress();
    setStatus(`Could not load visualizer data: ${error.message}`);
  }
}

async function loadView() {
  const params = viewParams();
  const url = `${API_VIEW}?${params.toString()}`;
  const requestId = state.viewRequestId + 1;
  state.viewRequestId = requestId;
  startTopProgress("Updating flow columns...", { indeterminate: true });
  await nextFrame();
  try {
    const view = await fetchJson(url);
    if (requestId !== state.viewRequestId) {
      return;
    }
    state.view = view;
    state.filters = { ...state.view.filters };
    state.geoSelection = normalizeGeoSelection(state.view.geo_filter, state.geoSelection);
    state.selectedMapKey = state.geoSelection ? state.geoSelection.key : "";
    updateTopProgress(24, { indeterminate: false, message: "Rendering runbook view..." });
    await render(requestId);
    if (requestId !== state.viewRequestId) {
      return;
    }
    finishTopProgress(buildReadyStatus());
  } catch (error) {
    if (requestId !== state.viewRequestId) {
      return;
    }
    stopTopProgress();
    setStatus(`Could not update view: ${error.message}`);
  }
}

async function fetchJson(url, options = {}) {
  const method = String(options.method || "GET").toUpperCase();
  const requestUrl = method === "GET" ? cacheBustedUrl(url) : url;
  const response = await fetch(requestUrl, { cache: "no-store", ...options });
  const contentType = response.headers.get("content-type") || "";
  const text = await response.text();
  let payload;
  if (contentType.includes("application/json")) {
    try {
      payload = JSON.parse(text);
    } catch (error) {
      throw new Error(`Visualizer API returned invalid JSON from ${requestUrl}: ${error.message}`);
    }
  } else {
    const hint = text.trim().startsWith("<!DOCTYPE")
      ? " The page is probably opened from a static server or an old port; use the Dock-1 runner URL."
      : "";
    throw new Error(`Visualizer API returned ${contentType || "non-JSON"} from ${requestUrl}.${hint}`);
  }
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || response.statusText);
  }
  return payload;
}

async function render(requestId = state.viewRequestId) {
  const stages = [
    {
      label: "Updating metrics...",
      work: () => {
        renderMetrics();
        renderMapControls();
      },
    },
    { label: "Updating coordinate map...", work: () => renderTopMap(requestId) },
    { label: "Updating statistics...", work: () => renderStatistics() },
    { label: "Updating flow columns...", work: () => renderWizard(requestId) },
    { label: "Updating row preview...", work: () => renderResults(requestId) },
    { label: "Updating selected coordinate...", work: () => renderRefinedMap() },
    { label: "Updating debug panel...", work: () => renderDebug() },
  ];

  for (let index = 0; index < stages.length; index += 1) {
    if (requestId !== state.viewRequestId) {
      return;
    }
    const stage = stages[index];
    updateTopProgress(24 + (index / stages.length) * 70, { message: stage.label });
    await nextFrame();
    await stage.work();
    updateTopProgress(24 + ((index + 1) / stages.length) * 70);
  }
}

function renderMetrics() {
  const view = state.view || {};
  const manifest = state.manifest || {};
  const knownIpCount = Math.max(Number(view.known_ip_count || 0), Number(manifest.known_ip_count || 0));
  const matchingIpCount = Number(view.matching_known_ip_count || 0);
  const rawMatchingCount = Number(view.raw_matching_count || 0);
  const aggregateRows = Number(view.matching_count || 0);
  elements.sourceFormat.textContent = uppercase(view.source_format || manifest.source_format || "-");
  elements.shardCount.textContent = numberFormatter.format((view.shards || manifest.shards || []).length);
  elements.totalRows.textContent = numberFormatter.format(knownIpCount);
  elements.totalRows.title = `${numberFormatter.format(knownIpCount)} distinct known IPs loaded from ${numberFormatter.format(
    view.total_rows || manifest.total_rows || 0,
  )} raw rows.`;
  elements.matchingRows.textContent = numberFormatter.format(matchingIpCount);
  elements.matchingRows.title = `${numberFormatter.format(matchingIpCount)} distinct IPs match the current filters. ${numberFormatter.format(
    aggregateRows,
  )} aggregate table rows from ${numberFormatter.format(rawMatchingCount)} raw rows.`;
  elements.outputDir.textContent = manifest.output_dir || "-";
}

function buildReadyStatus() {
  const progress = state.manifest?.pipeline_progress || {};
  if (!progress.status) {
    return "Ready.";
  }
  if (progress.status !== "ok") {
    return `Ready. Pipeline progress state is ${progress.status}.`;
  }
  const phase = displayValue(progress.phase || "unknown");
  const targetsDone = Number(progress.processed_targets || 0);
  const targetsTotal = Number(progress.selected_targets || 0);
  const activeChunk = progress.active_chunk && typeof progress.active_chunk === "object" ? progress.active_chunk : null;
  const activeChunkNumber = Number(activeChunk?.chunk_number || progress.current_chunk || 0);
  const activeChunkDone = Number(activeChunk?.completed_targets || 0);
  const activeChunkTotal = Number(activeChunk?.target_count || 0);
  const activeChunkText = activeChunkNumber
    ? ` chunk ${numberFormatter.format(activeChunkNumber)}${
        activeChunkTotal
          ? ` (${numberFormatter.format(activeChunkDone)}/${numberFormatter.format(activeChunkTotal)} current targets)`
          : ""
      }:`
    : ":";
  if (targetsTotal) {
    const targetPercent = Number(progress.target_percent || 0).toFixed(2);
    const skippedRanges = Number(progress.skipped_redundant_ranges || 0);
    const skippedText = skippedRanges ? ` ${numberFormatter.format(skippedRanges)} redundant ranges skipped.` : "";
    return `Ready. Pipeline ${phase}${activeChunkText} ${numberFormatter.format(targetsDone)}/${numberFormatter.format(
      targetsTotal,
    )} expanded IP targets (${targetPercent}%).${skippedText}`;
  }
  const rangesDone = numberFormatter.format(progress.processed_ranges || 0);
  const rangesTotal = numberFormatter.format(progress.selected_ranges || 0);
  const addressesDone = numberFormatter.format(progress.processed_addresses || 0);
  const addressesTotal = numberFormatter.format(progress.selected_addresses || 0);
  const rangePercent = Number(progress.range_percent || 0).toFixed(2);
  const addressPercent = Number(progress.address_percent || 0).toFixed(2);
  return `Ready. Pipeline ${phase}: ${rangesDone}/${rangesTotal} range targets (${rangePercent}%), ${addressesDone}/${addressesTotal} addresses covered (${addressPercent}%).`;
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
  state.map.on(
    "moveend zoomend",
    debounce(() => {
      if ((state.view && state.view.map_chunked) || (state.manifest && state.manifest.map_chunked)) {
        scheduleMapChunkLoad();
      }
    }, 120),
  );

  state.refinedMap = createMap(elements.refinedMap).setView([39.5, -98.35], 1);
  state.refinedMarkerLayer = L.layerGroup().addTo(state.refinedMap);
  bindZoomSlider(state.map, elements.mapZoomSlider);
  bindZoomSlider(state.refinedMap, elements.refinedMapZoomSlider);
}

function createMap(element) {
  const map = L.map(element, {
    preferCanvas: true,
    scrollWheelZoom: false,
    wheelPxPerZoomLevel: 720,
    worldCopyJump: true,
    zoomDelta: 0.25,
    zoomSnap: 0.05,
  });

  L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
    attribution: "&copy; OpenStreetMap contributors &copy; CARTO",
    maxZoom: 19,
  }).addTo(map);

  map.on("click", () => {
    map.scrollWheelZoom.enable();
  });
  map.on("mouseout", () => {
    map.scrollWheelZoom.disable();
  });

  window.setTimeout(() => map.invalidateSize(), 0);
  return map;
}

function bindZoomSlider(map, slider) {
  if (!map || !slider) {
    return;
  }
  const sync = () => {
    slider.value = String(map.getZoom());
  };
  slider.addEventListener("input", () => {
    map.setZoom(Number(slider.value), { animate: false });
  });
  map.on("zoom zoomend", sync);
  sync();
}

function defaultMapHeight() {
  const lower = window.innerWidth <= 860 ? 320 : 500;
  const upper = window.innerWidth <= 860 ? 620 : 880;
  return clampNumber(Math.round(window.innerHeight * 0.64), lower, upper);
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

async function renderTopMap(requestId = state.viewRequestId) {
  const view = state.view || {};
  const points = Array.isArray(view.map_points) ? view.map_points : [];
  const totalPoints = view.map_point_count || points.length;

  if (view.map_chunked || state.manifest?.map_chunked) {
    renderChunkedTopMap(view, totalPoints);
    return;
  }

  if (!state.map || !state.markerLayer) {
    elements.mapSummary.textContent = `${numberFormatter.format(totalPoints)} mapped IPs.`;
    return;
  }

  state.markerLayer.clearLayers();
  elements.mapSummary.textContent = buildMapSummary(view, totalPoints);

  const validPoints = validMapPoints(points);
  if (!validPoints.length) {
    state.currentMapBounds = [];
    state.selectedMapPoint = null;
    renderMapDetail(null);
    return;
  }

  const bounds = [];
  let selectedPoint = null;
  for (let start = 0; start < validPoints.length; start += MAP_MARKER_RENDER_CHUNK_SIZE) {
    if (requestId !== state.viewRequestId) {
      return;
    }
    validPoints.slice(start, start + MAP_MARKER_RENDER_CHUNK_SIZE).forEach((point) => {
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
    if (start + MAP_MARKER_RENDER_CHUNK_SIZE < validPoints.length) {
      updateTopProgress(30 + (start / validPoints.length) * 18, {
        message: `Plotting ${numberFormatter.format(
          Math.min(start + MAP_MARKER_RENDER_CHUNK_SIZE, validPoints.length),
        )}/${numberFormatter.format(validPoints.length)} map points...`,
      });
      await nextFrame();
    }
  }

  state.currentMapBounds = bounds;
  state.selectedMapPoint = selectedPoint;
  renderMapDetail(selectedPoint);
}

function renderChunkedTopMap(view, totalPoints) {
  if (!state.map || !state.markerLayer) {
    elements.mapSummary.textContent = `${numberFormatter.format(totalPoints)} map cells.`;
    return;
  }

  elements.mapSummary.textContent = buildMapSummary(view, totalPoints);
  if (!state.mapChunkInitialized) {
    state.mapChunkInitialized = true;
    state.markerLayer.clearLayers();
    state.currentMapBounds = [];
    state.selectedMapPoint = null;
    renderMapDetail(null);
  }
  scheduleMapChunkLoad(0);
}

function scheduleMapChunkLoad(delay = 120) {
  if (!state.map || !state.markerLayer) {
    return;
  }
  if (state.mapChunkLoadTimer) {
    clearTimeout(state.mapChunkLoadTimer);
  }
  state.mapChunkLoadTimer = setTimeout(() => {
    state.mapChunkLoadTimer = null;
    void loadMapChunks();
  }, delay);
}

async function loadMapChunks() {
  if (!state.map || !state.markerLayer) {
    return;
  }
  const bounds = state.map.getBounds();
  const params = new URLSearchParams();
  params.set("zoom", String(state.map.getZoom()));
  params.set("north", String(bounds.getNorth()));
  params.set("south", String(bounds.getSouth()));
  params.set("east", String(bounds.getEast()));
  params.set("west", String(bounds.getWest()));

  const requestId = state.mapChunkRequestId + 1;
  state.mapChunkRequestId = requestId;
  try {
    const payload = await fetchJson(`${API_MAP_CHUNKS}?${params.toString()}`);
    if (requestId !== state.mapChunkRequestId) {
      return;
    }
    state.mapChunkPayload = payload;
    renderMapChunkPayload(payload);
  } catch (error) {
    if (requestId === state.mapChunkRequestId) {
      elements.mapSummary.textContent = `Could not load map chunks: ${error.message}`;
    }
  }
}

function renderMapChunkPayload(payload) {
  const points = Array.isArray(payload.points) ? payload.points : [];
  const validPoints = validMapPoints(points);
  state.markerLayer.clearLayers();

  const bounds = [];
  let selectedPoint = null;
  validPoints.forEach((point) => {
    const selected = Boolean(state.geoSelection && state.geoSelection.key === point.key);
    if (selected && state.selectedMapPoint && Array.isArray(state.selectedMapPoint.cache_records)) {
      point = {
        ...point,
        cache_records: state.selectedMapPoint.cache_records,
        record_count: state.selectedMapPoint.record_count || point.record_count,
      };
    }
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
  state.selectedMapPoint = selectedPoint || state.selectedMapPoint;
  renderMapDetail(selectedPoint || state.selectedMapPoint || null);
  elements.mapSummary.textContent = buildChunkedMapSummary(payload, validPoints.length);
}

async function loadSelectedMapRecords(point) {
  if (!point || !point.records_path) {
    return;
  }
  if (Array.isArray(point.cache_records) && point.cache_records.length) {
    renderMapDetail(point);
    renderRefinedMap();
    return;
  }

  const requestId = state.mapSelectionRequestId + 1;
  state.mapSelectionRequestId = requestId;
  const params = new URLSearchParams();
  params.set("path", point.records_path);
  try {
    const payload = await fetchJson(`${API_MAP_SELECTION}?${params.toString()}`);
    if (requestId !== state.mapSelectionRequestId || !state.geoSelection || state.geoSelection.key !== point.key) {
      return;
    }
    const records = Array.isArray(payload.records) ? payload.records : [];
    const merged = {
      ...point,
      cache_records: records,
      record_count: Number(payload.record_count || records.length || point.record_count || 0),
    };
    state.selectedMapPoint = merged;
    renderMapDetail(merged);
    renderRefinedMap();
    scheduleMapChunkLoad(0);
  } catch (error) {
    if (requestId === state.mapSelectionRequestId && state.geoSelection && state.geoSelection.key === point.key) {
      const failed = {
        ...point,
        selection_error: error.message,
      };
      state.selectedMapPoint = failed;
      renderMapDetail(failed);
      renderRefinedMap();
    }
  }
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
    top: { color: "#36d878", fillColor: "#effaf2" },
    selected: { color: "#6dffa6", fillColor: "#ffffff" },
    refined: { color: "#1ba65a", fillColor: "#dfffee" },
  };
  const style = styles[mode] || styles.top;

  return L.circleMarker([point.latNumber, point.longNumber], {
    radius: Math.min(18, 6 + Math.sqrt(ipCount)),
    weight: 2,
    color: style.color,
    fillColor: style.fillColor,
    fillOpacity: 0.88,
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
    color: "#36d878",
    fillColor: "#effaf2",
    fillOpacity: 0.86,
  });
}

function buildMapSummary(view, totalPoints) {
  const mappedIps = numberFormatter.format(view.mapped_ip_count || 0);
  const pointText = numberFormatter.format(totalPoints);
  const ok = numberFormatter.format(view.coordinate_lookup_ok_count || 0);
  const errors = numberFormatter.format(view.coordinate_lookup_error_count || 0);
  const geoText = state.geoSelection ? ` Selected: ${state.geoSelection.label || state.geoSelection.key}.` : "";
  return `${pointText} map points, ${mappedIps} mapped IPs. Lookups: ${ok} ok, ${errors} not mapped.${geoText}`;
}

function buildChunkedMapSummary(payload, visiblePoints) {
  const visible = numberFormatter.format(visiblePoints);
  const total = numberFormatter.format(payload.total_points || 0);
  const mappedIps = numberFormatter.format(payload.mapped_ip_count || 0);
  const chunks = numberFormatter.format(payload.loaded_chunks || 0);
  const level = payload.level ? ` at ${payload.level}` : "";
  const geoText = state.geoSelection ? ` Selected: ${state.geoSelection.label || state.geoSelection.key}.` : "";
  return `${visible}/${total} visible map cells${level}, ${mappedIps} mapped IPs represented, ${chunks} chunks loaded.${geoText}`;
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
  if (!dots.length) {
    if (point.selection_error) {
      return `Could not load selected server records: ${point.selection_error}`;
    }
    if (point.records_path) {
      return `${numberFormatter.format(ipCount)} servers represented by this map cell. Loading selected IP records...`;
    }
    return `${numberFormatter.format(ipCount)} servers represented by this map cell. Zoom in for finer coordinate chunks.`;
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
    map.fitBounds(bounds, { padding: [12, 12] });
  }
}

function selectMapRegion(point) {
  const ips = Array.isArray(point.ips) ? point.ips.map(String).filter(Boolean) : [];
  state.geoSelection = {
    key: point.key,
    label: locationLabel(point) || point.key,
    ips,
    bbox: point.bbox || null,
    level: point.level || "",
  };
  state.selectedMapKey = point.key;
  state.selectedMapPoint = point;
  state.columnSearches = {};
  state.resultSearch = "";
  elements.resultsSearch.value = "";
  renderMapControls();
  renderMapDetail(point);
  renderRefinedMap();
  void loadSelectedMapRecords(point);
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
  renderMapDetail(null);
  renderRefinedMap();
  scheduleMapChunkLoad(0);
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
    ["Long", record.long],
    ["Lat", record.lat],
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
    empty.textContent = "Select a map point to inspect its IPs and coordinates.";
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
  ["IP", "Long", "Lat", "Provider", "Ping", "Org", "ASN", "Looked Up"].forEach((label) => {
    const th = document.createElement("th");
    th.textContent = label;
    headRow.appendChild(th);
  });
  thead.appendChild(headRow);

  const tbody = document.createElement("tbody");
  const records = Array.isArray(point.cache_records) ? point.cache_records : [];
  if (!records.length) {
    const row = document.createElement("tr");
    const td = document.createElement("td");
    td.className = "empty-state";
    td.colSpan = 8;
    td.textContent = point.selection_error
      ? `Could not load selected IP records: ${point.selection_error}`
      : point.records_path
        ? "Loading selected IP records..."
        : "No selected IP records were attached to this map point.";
    row.appendChild(td);
    tbody.appendChild(row);
  }
  records.forEach((record) => {
    const row = document.createElement("tr");
    [
      record.ip,
      record.long,
      record.lat,
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

function renderStatistics() {
  if (!elements.statsGrid) {
    return;
  }
  elements.statsGrid.textContent = "";
  const stats = state.view?.statistics || {};

  const cards = Array.isArray(stats.cards) ? stats.cards : [];
  if (cards.length) {
    const stack = document.createElement("article");
    stack.className = "stat-card stat-stack";
    cards.forEach((card) => {
      const wrapper = document.createElement("div");
      wrapper.className = "stat-stack-row";
      const label = document.createElement("span");
      label.textContent = displayValue(card.label || "");
      const value = document.createElement("strong");
      value.textContent = numberFormatter.format(Number(card.value || 0));
      wrapper.append(label, value);
      stack.appendChild(wrapper);
    });
    elements.statsGrid.appendChild(stack);
  }

  (Array.isArray(stats.pies) ? stats.pies : []).slice(0, 5).forEach((pie, index) => {
    elements.statsGrid.appendChild(renderPieChart(pie, index));
  });

  const scanDays = Array.isArray(stats.scan_days) ? stats.scan_days : [];
  elements.statsGrid.appendChild(renderLineChart("Scanned At by day", scanDays));
}

function renderPieChart(pie, chartIndex) {
  const colors = ["#36d878", "#effaf2", "#1ba65a", "#9fb0a8", "#6dffa6", "#24884f", "#f0b35a"];
  const card = document.createElement("article");
  card.className = "chart-card";
  const title = document.createElement("span");
  title.className = "chart-title";
  title.textContent = displayValue(pie.title || "Distribution");
  const layout = document.createElement("div");
  layout.className = "pie-layout";
  const dial = document.createElement("div");
  dial.className = "pie-dial";
  const legend = document.createElement("div");
  legend.className = "chart-legend";
  const items = (Array.isArray(pie.items) ? pie.items : []).filter(
    (item) => Number(item.count || 0) > 0 && displayValue(item.label || "") !== "(blank)",
  );
  const total = items.reduce((sum, item) => sum + Number(item.count || 0), 0);
  let cursor = 0;
  const stops = items.map((item, index) => {
    const count = Number(item.count || 0);
    const start = cursor;
    cursor += total ? (count / total) * 100 : 0;
    const color = colors[(chartIndex + index) % colors.length];
    renderLegendRow(legend, color, displayValue(item.label || ""), count);
    return `${color} ${start.toFixed(2)}% ${cursor.toFixed(2)}%`;
  });
  dial.style.background = stops.length ? `conic-gradient(${stops.join(", ")})` : "#0b100e";
  layout.append(dial, legend);
  card.append(title, layout);
  return card;
}

function renderLegendRow(parent, color, label, count) {
  const row = document.createElement("div");
  row.className = "legend-row";
  const swatch = document.createElement("span");
  swatch.className = "legend-swatch";
  swatch.style.background = color;
  const text = document.createElement("span");
  text.className = "legend-label";
  text.textContent = label;
  text.title = label;
  const value = document.createElement("span");
  value.textContent = numberFormatter.format(count);
  row.append(swatch, text, value);
  parent.appendChild(row);
}

function renderLineChart(titleText, points) {
  const card = document.createElement("article");
  card.className = "chart-card";
  const title = document.createElement("span");
  title.className = "chart-title";
  title.textContent = titleText;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "line-chart");
  svg.setAttribute("viewBox", "0 0 360 240");
  svg.setAttribute("preserveAspectRatio", "none");
  if (!points.length) {
    const empty = document.createElement("p");
    empty.className = "note";
    empty.textContent = "No scanned-at dates loaded.";
    card.append(title, empty);
    return card;
  }
  const max = Math.max(...points.map((point) => Number(point.count || 0)), 1);
  const plot = { left: 42, right: 344, top: 28, bottom: 204 };
  const axisLabel = document.createElementNS("http://www.w3.org/2000/svg", "text");
  axisLabel.setAttribute("x", "14");
  axisLabel.setAttribute("y", "120");
  axisLabel.setAttribute("fill", "#9fb0a8");
  axisLabel.setAttribute("font-size", "9");
  axisLabel.setAttribute("text-anchor", "middle");
  axisLabel.setAttribute("transform", "rotate(-90 14 120)");
  axisLabel.textContent = "Scans";
  svg.appendChild(axisLabel);
  const maxLabel = document.createElementNS("http://www.w3.org/2000/svg", "text");
  maxLabel.setAttribute("x", String(plot.left - 6));
  maxLabel.setAttribute("y", String(plot.top + 4));
  maxLabel.setAttribute("fill", "#9fb0a8");
  maxLabel.setAttribute("font-size", "9");
  maxLabel.setAttribute("text-anchor", "end");
  maxLabel.textContent = numberFormatter.format(max);
  svg.appendChild(maxLabel);
  const grid = document.createElementNS("http://www.w3.org/2000/svg", "line");
  grid.setAttribute("x1", String(plot.left));
  grid.setAttribute("x2", String(plot.right));
  grid.setAttribute("y1", String(plot.bottom));
  grid.setAttribute("y2", String(plot.bottom));
  grid.setAttribute("stroke", "rgba(159, 176, 168, 0.26)");
  grid.setAttribute("stroke-width", "1");
  grid.setAttribute("vector-effect", "non-scaling-stroke");
  svg.appendChild(grid);
  const polyline = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
  const coordinates = points.map((point, index) => {
    const x = points.length <= 1 ? (plot.left + plot.right) / 2 : plot.left + (index / (points.length - 1)) * (plot.right - plot.left);
    const y = plot.bottom - (Number(point.count || 0) / max) * (plot.bottom - plot.top);
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  });
  if (points.length > 1) {
    const area = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
    area.setAttribute(
      "points",
      `${plot.left},${plot.bottom} ${coordinates.join(" ")} ${plot.right},${plot.bottom}`,
    );
    area.setAttribute("fill", "rgba(54, 216, 120, 0.12)");
    svg.appendChild(area);
  }
  polyline.setAttribute("points", coordinates.join(" "));
  polyline.setAttribute("fill", "none");
  polyline.setAttribute("stroke", "#36d878");
  polyline.setAttribute("stroke-width", "2");
  polyline.setAttribute("vector-effect", "non-scaling-stroke");
  svg.appendChild(polyline);
  if (points.length === 1) {
    const [x, y] = coordinates[0].split(",").map(Number);
    const bar = document.createElementNS("http://www.w3.org/2000/svg", "line");
    bar.setAttribute("x1", String(x));
    bar.setAttribute("x2", String(x));
    bar.setAttribute("y1", String(plot.bottom));
    bar.setAttribute("y2", String(y));
    bar.setAttribute("stroke", "rgba(54, 216, 120, 0.72)");
    bar.setAttribute("stroke-width", "16");
    bar.setAttribute("stroke-linecap", "round");
    bar.setAttribute("vector-effect", "non-scaling-stroke");
    const dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    dot.setAttribute("cx", String(x));
    dot.setAttribute("cy", String(y));
    dot.setAttribute("r", "5");
    dot.setAttribute("fill", "#effaf2");
    dot.setAttribute("stroke", "#36d878");
    dot.setAttribute("stroke-width", "2");
    const valueLabel = document.createElementNS("http://www.w3.org/2000/svg", "text");
    valueLabel.setAttribute("x", String(x));
    valueLabel.setAttribute("y", String(Math.max(14, y - 12)));
    valueLabel.setAttribute("fill", "#effaf2");
    valueLabel.setAttribute("font-size", "10");
    valueLabel.setAttribute("font-weight", "700");
    valueLabel.setAttribute("text-anchor", "middle");
    valueLabel.textContent = numberFormatter.format(Number(points[0].count || 0));
    svg.appendChild(bar);
    svg.appendChild(dot);
    svg.appendChild(valueLabel);
  }
  const meta = document.createElement("p");
  meta.className = "line-chart-meta";
  if (points.length === 1) {
    meta.textContent = `${displayValue(points[0].day || "")}: ${numberFormatter.format(Number(points[0].count || 0))} scans`;
  } else {
    const first = points[0];
    const last = points[points.length - 1];
    meta.textContent = `${displayValue(first.day || "")} - ${displayValue(last.day || "")}`;
  }
  card.append(title, svg, meta);
  return card;
}

async function renderWizard(requestId = state.viewRequestId) {
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

  for (let index = 0; index < view.columns.length; index += 1) {
    if (requestId !== state.viewRequestId) {
      return;
    }
    const column = view.columns[index];
    const rendered = renderColumn(column, index);
    elements.wizardColumns.appendChild(rendered.wrapper);
    updateTopProgress(55 + (index / view.columns.length) * 16, {
      message: `Updating flow columns ${numberFormatter.format(index + 1)}/${numberFormatter.format(
        view.columns.length,
      )}...`,
    });
    if (rendered.page.search) {
      void loadColumnOptions(rendered.page.field, true);
    } else {
      rendered.page.loading = true;
      renderColumnFooter(rendered.page);
      await applyColumnPayload(rendered.page, column, true, requestId);
      rendered.page.loading = false;
      renderColumnFooter(rendered.page);
    }
    await nextFrame();
  }
}

function renderColumn(column, index) {
  const field = column.field;
  const hasSelectedValue = Object.prototype.hasOwnProperty.call(state.filters, field);
  const selectedValue = hasSelectedValue ? state.filters[field] : ANY_VALUE;
  const wrapper = document.createElement("article");
  wrapper.className = "flow-column";

  const resetButton = document.createElement("button");
  resetButton.type = "button";
  resetButton.className = "button secondary small column-reset-button";
  resetButton.textContent = "Reset";
  resetButton.disabled = !hasSelectedValue;
  resetButton.addEventListener("click", () => {
    setFilter(field, ANY_VALUE, index);
  });

  const header = document.createElement("div");
  header.className = "column-header";
  const title = document.createElement("h3");
  title.textContent = labelFor(field);
  const detail = document.createElement("p");
  const selectedText = hasSelectedValue ? `, selected ${displayValue(selectedValue)}` : "";
  const ipText = numberFormatter.format(column.matched_ip_count || 0);
  const rowText = numberFormatter.format(column.matched_rows || 0);
  const valueText = numberFormatter.format(column.unsearched_total_options || column.total_options || 0);
  detail.textContent = `${ipText} known IPs represented (${rowText} rows, ${valueText} values)${selectedText}`;
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

  actions.append(searchLabel);
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
    matchedIpCount: Number(column.matched_ip_count || 0),
    matchedRows: Number(column.matched_rows || 0),
    hasMore: false,
    loading: false,
  };
  state.columnPaging[field] = page;

  setListMessage(list, page.search ? "Searching values..." : "Loading values...");
  renderColumnFooter(page);

  wrapper.append(resetButton, header, selectWrap, list, footer);
  return { wrapper, page };
}

async function applyColumnPayload(page, payload, reset, requestId = state.viewRequestId) {
  if (reset) {
    page.list.textContent = "";
  }
  const options = Array.isArray(payload.options) ? payload.options : [];
  page.offset = Number(payload.offset || 0);
  page.total = Number(payload.total_options || 0);
  page.matchedIpCount = Number(payload.matched_ip_count || page.matchedIpCount || 0);
  page.matchedRows = Number(payload.matched_rows || page.matchedRows || 0);
  page.hasMore = Boolean(payload.has_more);
  await appendColumnOptions(page, options, requestId);
  page.offset += options.length;
  if (!page.offset && !options.length) {
    setListMessage(page.list, page.search ? "No values match this search." : "No values match the current path.");
  }
  renderColumnFooter(page);
}

async function appendColumnOptions(page, options, requestId = state.viewRequestId) {
  for (let start = 0; start < options.length; start += OPTION_RENDER_CHUNK_SIZE) {
    if (requestId !== state.viewRequestId) {
      return;
    }
    const fragment = document.createDocumentFragment();
    options.slice(start, start + OPTION_RENDER_CHUNK_SIZE).forEach((option) => {
      const button = document.createElement("button");
      button.type = "button";
      const isActive =
        Object.prototype.hasOwnProperty.call(state.filters, page.field) && option.value === state.filters[page.field];
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
      const ipCount = Number(option.ip_count || option.count || 0);
      const rowCount = Number(option.row_count || option.count || 0);
      count.textContent = numberFormatter.format(ipCount);
      count.title = `${numberFormatter.format(ipCount)} IPs, ${numberFormatter.format(rowCount)} rows`;

      button.append(value, count);
      fragment.appendChild(button);
    });
    page.list.appendChild(fragment);
    if (start + OPTION_RENDER_CHUNK_SIZE < options.length) {
      await nextFrame();
    }
  }
}

function renderColumnFooter(page) {
  page.footer.textContent = "";

  const status = document.createElement("p");
  status.className = "column-status";
  if (page.loading) {
    status.textContent = "Loading more values...";
  } else if (!page.total) {
    status.textContent = `${numberFormatter.format(page.matchedIpCount || 0)} known IPs represented. No values to show.`;
  } else if (page.hasMore) {
    status.textContent = `${numberFormatter.format(page.matchedIpCount || 0)} known IPs represented (${numberFormatter.format(
      page.matchedRows || 0,
    )} rows). Showing ${numberFormatter.format(page.offset)} of ${numberFormatter.format(
      page.total,
    )} values. Scroll this list for more.`;
  } else {
    status.textContent = `${numberFormatter.format(page.matchedIpCount || 0)} known IPs represented (${numberFormatter.format(
      page.matchedRows || 0,
    )} rows). Showing all ${numberFormatter.format(page.total)} values.`;
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
    await applyColumnPayload(page, payload, reset);
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

function maybeLoadVisibleColumnOptions() {
  Object.keys(state.columnPaging).forEach((field) => {
    const page = state.columnPaging[field];
    if (!page || page.loading || !page.hasMore) {
      return;
    }
    if (isNearViewportBottom(page.list, 700)) {
      void loadColumnOptions(field, false);
    }
  });
}

async function renderResults(requestId = state.viewRequestId) {
  const view = state.view;
  elements.resultsHead.textContent = "";
  elements.resultsBody.textContent = "";

  if (!view || !Array.isArray(view.headers) || !view.headers.length) {
    elements.previewNote.textContent = "";
    return;
  }

  elements.resultsSearch.value = state.resultSearch;

  const headerRow = document.createElement("tr");
  const copyHeader = document.createElement("th");
  copyHeader.className = "row-copy-header";
  copyHeader.textContent = "Copy";
  headerRow.appendChild(copyHeader);
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
  await appendRows(rows, requestId);
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
    await appendRows(rows);
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

async function appendRows(rows, requestId = state.viewRequestId) {
  const view = state.view;
  for (let start = 0; start < rows.length; start += ROW_RENDER_CHUNK_SIZE) {
    if (requestId !== state.viewRequestId) {
      return;
    }
    const fragment = document.createDocumentFragment();
    rows.slice(start, start + ROW_RENDER_CHUNK_SIZE).forEach((row) => {
      const tr = document.createElement("tr");
      const actionCell = document.createElement("td");
      actionCell.className = "row-copy-cell";
      const copyButton = document.createElement("button");
      copyButton.type = "button";
      copyButton.className = "button secondary row-copy-button";
      copyButton.textContent = "Copy";
      copyButton.title = "Copy row JSONL";
      copyButton.addEventListener("click", () => {
        void copyRowJsonl(row, view.headers, copyButton);
      });
      actionCell.appendChild(copyButton);
      tr.appendChild(actionCell);
      view.headers.forEach((header) => {
        const td = document.createElement("td");
        const value = row[header] || "";
        td.textContent = displayValue(value);
        if (!value) {
          td.className = "blank";
        }
        tr.appendChild(td);
      });
      fragment.appendChild(tr);
    });
    elements.resultsBody.appendChild(fragment);
    if (start + ROW_RENDER_CHUNK_SIZE < rows.length) {
      await nextFrame();
    }
  }
}

async function copyRowJsonl(row, headers, button) {
  const jsonl = `${JSON.stringify(rowCharacteristics(row, headers))}\n`;
  try {
    await copyTextToClipboard(jsonl);
    setStatus("Copied row JSONL to clipboard.");
    flashButtonLabel(button, "Copied");
  } catch (error) {
    setStatus(`Copy failed: ${error.message}`);
  }
}

function rowCharacteristics(row, headers) {
  const output = {};
  headers.forEach((header) => {
    const value = row[header];
    if (value !== undefined && value !== null && String(value) !== "") {
      output[header] = value;
    }
  });
  return output;
}

async function copyTextToClipboard(text) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.top = "-1000px";
  document.body.appendChild(textarea);
  textarea.select();
  try {
    if (!document.execCommand("copy")) {
      throw new Error("Clipboard copy was rejected.");
    }
  } finally {
    textarea.remove();
  }
}

function flashButtonLabel(button, label) {
  if (!button) {
    return;
  }
  const original = button.textContent;
  button.textContent = label;
  window.setTimeout(() => {
    button.textContent = original;
  }, 1100);
}

function maybeLoadMoreRows() {
  if (state.resultPaging.loading || !state.resultPaging.hasMore) {
    return;
  }
  const canScrollLocally = elements.tableWrap.scrollHeight > elements.tableWrap.clientHeight + 1;
  const localScrollBottom =
    canScrollLocally &&
    elements.tableWrap.scrollTop + elements.tableWrap.clientHeight >= elements.tableWrap.scrollHeight - SCROLL_THRESHOLD;
  if (localScrollBottom || isNearViewportBottom(elements.tableWrap, 900)) {
    void loadRows(false);
  }
}

function isNearViewportBottom(element, margin = SCROLL_THRESHOLD) {
  if (!element) {
    return false;
  }
  return element.getBoundingClientRect().bottom <= window.innerHeight + margin;
}

function showRowsMessage(message) {
  const view = state.view;
  const tr = document.createElement("tr");
  const td = document.createElement("td");
  td.className = "empty-state";
  td.colSpan = view && Array.isArray(view.headers) ? view.headers.length + 1 : 1;
  td.textContent = message;
  tr.appendChild(td);
  elements.resultsBody.textContent = "";
  elements.resultsBody.appendChild(tr);
}

function updateResultsNote() {
  const visible = state.resultPaging.offset;
  const total = state.resultPaging.total;
  const searchText = state.resultSearch.trim() ? " search" : "";
  const rawRows = Number(state.view?.raw_matching_count || 0);
  const rawText = rawRows && rawRows !== total ? ` from ${numberFormatter.format(rawRows)} raw rows` : "";
  if (state.resultPaging.loading) {
    elements.previewNote.textContent = "Loading rows...";
  } else if (state.resultPaging.hasMore) {
    elements.previewNote.textContent = `Showing ${numberFormatter.format(visible)} of ${numberFormatter.format(
      total,
    )}${searchText} aggregate rows${rawText}. Scroll for more.`;
  } else {
    elements.previewNote.textContent = `${numberFormatter.format(total)}${searchText} aggregate rows${rawText}.`;
  }
}

function renderDebug() {
  if (!elements.debugBody) {
    return;
  }
  elements.debugBody.textContent = "";
  const debug = state.view?.debug || {};
  const errorCount = Number(debug.error_row_count || 0);
  const summary = document.createElement("p");
  summary.className = "note";
  summary.textContent = errorCount
    ? `${numberFormatter.format(errorCount)} rows include error text.`
    : "No error text found in the current selection.";
  elements.debugBody.appendChild(summary);

  if (!errorCount) {
    return;
  }

  const grid = document.createElement("div");
  grid.className = "debug-grid";
  const listPanel = document.createElement("section");
  listPanel.className = "debug-list";
  const listTitle = document.createElement("h3");
  listTitle.textContent = "Error groups";
  const list = document.createElement("ol");
  (Array.isArray(debug.errors) ? debug.errors : []).forEach((item) => {
    const entry = document.createElement("li");
    entry.textContent = `${numberFormatter.format(Number(item.count || 0))}: ${displayValue(item.label || "")}`;
    list.appendChild(entry);
  });
  listPanel.append(listTitle, list);

  const samplePanel = document.createElement("section");
  samplePanel.className = "debug-samples";
  const sampleTitle = document.createElement("h3");
  sampleTitle.textContent = "Samples";
  const sampleList = document.createElement("ol");
  (Array.isArray(debug.samples) ? debug.samples : []).forEach((sample) => {
    const entry = document.createElement("li");
    const host = sample.host ? `${sample.host} ` : "";
    const port = sample.port ? `:${sample.port} ` : "";
    entry.textContent = `${host}${port}${displayValue(sample.error || "")}`;
    sampleList.appendChild(entry);
  });
  samplePanel.append(sampleTitle, sampleList);
  grid.append(listPanel, samplePanel);
  elements.debugBody.appendChild(grid);
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

function cacheBustedUrl(url) {
  const parsed = new URL(url, window.location.origin);
  parsed.searchParams.set("_", String(Date.now()));
  return `${parsed.pathname}${parsed.search}`;
}

function geoFilterPayload() {
  if (!state.geoSelection) {
    return {};
  }
  const ips = Array.isArray(state.geoSelection.ips) ? state.geoSelection.ips : [];
  const payload = {
    key: state.geoSelection.key || "",
    label: state.geoSelection.label || "",
    ips: state.geoSelection.key && ips.length > 200 ? [] : ips,
  };
  if (state.geoSelection.bbox) {
    payload.bbox = state.geoSelection.bbox;
  }
  if (state.geoSelection.level) {
    payload.level = state.geoSelection.level;
  }
  return payload;
}

function normalizeGeoSelection(payload, previous) {
  if (!payload || typeof payload !== "object") {
    return null;
  }
  const ips = Array.isArray(payload.ips) ? payload.ips.map(String).filter(Boolean) : [];
  const key = String(payload.key || previous?.key || "");
  const label = String(payload.label || previous?.label || key);
  const bbox = payload.bbox && typeof payload.bbox === "object" ? payload.bbox : previous?.bbox || null;
  const level = String(payload.level || previous?.level || "");
  if (!key && !ips.length && !bbox) {
    return null;
  }
  return { key, label, ips, bbox, level };
}

function setListMessage(list, message) {
  list.textContent = "";
  const empty = document.createElement("p");
  empty.className = "empty-state";
  empty.textContent = message;
  list.appendChild(empty);
}

function startTopProgress(message, options = {}) {
  if (state.progressHideTimer) {
    window.clearTimeout(state.progressHideTimer);
    state.progressHideTimer = null;
  }
  setStatus(message);
  if (!elements.progress || !elements.progressBar) {
    return;
  }
  elements.progress.classList.add("is-active");
  elements.progress.classList.toggle("is-indeterminate", Boolean(options.indeterminate));
  elements.progressBar.style.width = `${clampNumber(Number(options.percent || 0), 0, 100)}%`;
}

function updateTopProgress(percent, options = {}) {
  if (options.message) {
    setStatus(options.message);
  }
  if (!elements.progress || !elements.progressBar) {
    return;
  }
  elements.progress.classList.toggle("is-indeterminate", Boolean(options.indeterminate));
  elements.progressBar.style.width = `${clampNumber(Number(percent || 0), 0, 100)}%`;
}

function finishTopProgress(message) {
  updateTopProgress(100, { message });
  if (!elements.progress || !elements.progressBar) {
    return;
  }
  if (state.progressHideTimer) {
    window.clearTimeout(state.progressHideTimer);
  }
  state.progressHideTimer = window.setTimeout(() => {
    stopTopProgress();
  }, PROGRESS_HIDE_DELAY);
}

function stopTopProgress() {
  if (state.progressHideTimer) {
    window.clearTimeout(state.progressHideTimer);
    state.progressHideTimer = null;
  }
  if (!elements.progress || !elements.progressBar) {
    return;
  }
  elements.progress.classList.remove("is-active", "is-indeterminate");
  elements.progressBar.style.width = "0%";
}

function setStatus(message) {
  elements.status.textContent = message;
}

function nextFrame() {
  return new Promise((resolve) => {
    window.requestAnimationFrame(() => resolve());
  });
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
