const DATA_URL = "../../data/private/visualizer/plants_reference.json";
const EMISSIONS_PREFIX = "emissions:";

const BASE_METRIC_DEFINITIONS = [
  { key: "operable_nameplate_capacity_mw", label: "Nameplate Capacity (MW)", source: "base" },
  { key: "operable_summer_capacity_mw", label: "Summer Capacity (MW)", source: "base" },
  { key: "operable_winter_capacity_mw", label: "Winter Capacity (MW)", source: "base" },
  { key: "generator_count", label: "Generator Count", source: "base" },
  { key: "carbon_capture_generator_count", label: "Carbon Capture Generator Count", source: "base" },
  { key: "co2_emissions_value", label: "CO2 Emissions (tons)", source: "base" },
  { key: "co2e_emissions_value", label: "CO2e Emissions (tons)", source: "base" },
  { key: "ch4_emissions_value", label: "CH4 Emissions (lb)", source: "base" },
  { key: "n2o_emissions_value", label: "N2O Emissions (lb)", source: "base" },
  { key: "so2_emissions_value", label: "SO2 Emissions", source: "base" },
  { key: "nox_emissions_value", label: "NOx Emissions (tons)", source: "base" },
  { key: "particulate_matter_emissions_value", label: "Particulate Matter Emissions", source: "base" },
  { key: "mercury_emissions_value", label: "Mercury Emissions (lb)", source: "base" },
  { key: "radioisotopic_emissions_value", label: "Radioisotopic Emissions", source: "base" },
];

const PREFERRED_UPLOADED_METRICS = [
  "co2_tons",
  "co2_mass_tons",
  "co2e_tons",
  "co2_equivalent_tons",
  "mercury_lb",
  "mercury_lbs",
  "so2_tons",
  "nox_tons",
];

const FUEL_COLORS = {
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

const state = {
  plants: [],
  metadata: null,
  filteredPlants: [],
  uploadedMetricDefinitions: [],
  activeMetricKey: BASE_METRIC_DEFINITIONS[0].key,
  activePlantCode: "",
  map: null,
  pointLayer: null,
  heatLayer: null,
  canvasRenderer: null,
  markerByCode: new Map(),
  uploadSummary: null,
};

const numberFormatter = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });
const integerFormatter = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

const elements = {
  emissionsFile: document.getElementById("emissions-file"),
  clearEmissions: document.getElementById("clear-emissions"),
  uploadSummary: document.getElementById("upload-summary"),
  metricSelect: document.getElementById("metric-select"),
  viewSelect: document.getElementById("view-select"),
  stateSelect: document.getElementById("state-select"),
  fuelSelect: document.getElementById("fuel-select"),
  searchInput: document.getElementById("search-input"),
  minimumInput: document.getElementById("minimum-input"),
  zoomFiltered: document.getElementById("zoom-filtered"),
  resetFilters: document.getElementById("reset-filters"),
  visibleCount: document.getElementById("visible-count"),
  metricTotal: document.getElementById("metric-total"),
  metricMax: document.getElementById("metric-max"),
  metricName: document.getElementById("metric-name"),
  resultsList: document.getElementById("results-list"),
  detailPanel: document.getElementById("detail-panel"),
  statusPill: document.getElementById("status-pill"),
};

document.addEventListener("DOMContentLoaded", () => {
  void init();
});

async function init() {
  bindEvents();
  buildMap();
  setStatus("Loading plant coordinate asset...");

  try {
    const response = await fetch(DATA_URL, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const payload = await response.json();
    state.metadata = payload.metadata;
    state.plants = payload.plants.map(hydratePlant);
    populateFilters();
    syncMetricOptions();
    setStatus(`Loaded ${integerFormatter.format(state.plants.length)} plant coordinates.`);
    refreshView({ fitBounds: true });
  } catch (error) {
    console.error(error);
    setStatus(
      "Could not load the private plant asset. Serve the repo root with a local HTTP server before opening this page.",
      "error",
    );
  }
}

function buildMap() {
  state.canvasRenderer = L.canvas({ padding: 0.35 });
  state.map = L.map("map", {
    preferCanvas: true,
    zoomSnap: 0.25,
    minZoom: 2,
  }).setView([39.8, -98.6], 4);

  L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
    attribution: "&copy; OpenStreetMap contributors &copy; CARTO",
    subdomains: "abcd",
    maxZoom: 19,
  }).addTo(state.map);

  state.pointLayer = L.layerGroup().addTo(state.map);
}

function bindEvents() {
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

  elements.fuelSelect.addEventListener("change", () => {
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
    elements.fuelSelect.value = "";
    elements.searchInput.value = "";
    elements.minimumInput.value = "";
    elements.viewSelect.value = "both";
    refreshView({ fitBounds: true });
  });

  elements.emissionsFile.addEventListener("change", async (event) => {
    const [file] = event.target.files ?? [];
    if (!file) {
      return;
    }
    await loadEmissionsFile(file);
  });

  elements.clearEmissions.addEventListener("click", () => {
    clearUploadedMetrics();
    elements.emissionsFile.value = "";
    refreshView();
  });
}

function hydratePlant(plant) {
  const baseMetrics = {};
  for (const definition of BASE_METRIC_DEFINITIONS) {
    baseMetrics[definition.key] = toNumber(plant[definition.key]);
  }

  return {
    ...plant,
    latitude: Number(plant.latitude),
    longitude: Number(plant.longitude),
    baseMetrics,
    uploadedMetrics: {},
    searchText: [
      plant.plant_code,
      plant.plant_name,
      plant.utility_name,
      plant.county,
      plant.city,
      plant.state,
      plant.primary_fuel_code,
    ]
      .join(" ")
      .toLowerCase(),
  };
}

function populateFilters() {
  const states = state.metadata?.states ?? [];
  const fuels = state.metadata?.fuel_codes ?? [];

  for (const value of states) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    elements.stateSelect.append(option);
  }

  for (const value of fuels) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    elements.fuelSelect.append(option);
  }
}

function currentMetricDefinitions() {
  return [...BASE_METRIC_DEFINITIONS, ...state.uploadedMetricDefinitions];
}

function syncMetricOptions() {
  const definitions = currentMetricDefinitions();
  const previousValue = state.activeMetricKey;
  const selectedValue = definitions.some((item) => item.key === previousValue)
    ? previousValue
    : preferredMetricKey(definitions);

  elements.metricSelect.replaceChildren();
  for (const definition of definitions) {
    const option = document.createElement("option");
    option.value = definition.key;
    option.textContent = definition.label;
    elements.metricSelect.append(option);
  }

  state.activeMetricKey = selectedValue;
  elements.metricSelect.value = selectedValue;
}

function preferredMetricKey(definitions) {
  for (const preferred of PREFERRED_UPLOADED_METRICS) {
    const found = definitions.find((item) => item.key === `${EMISSIONS_PREFIX}${preferred}`);
    if (found) {
      return found.key;
    }
  }
  return definitions[0]?.key ?? BASE_METRIC_DEFINITIONS[0].key;
}

function refreshView(options = {}) {
  state.filteredPlants = applyFilters();

  if (state.activePlantCode && !state.filteredPlants.some((plant) => plant.plant_code === state.activePlantCode)) {
    state.activePlantCode = "";
  }

  const metricStats = buildMetricStats(state.filteredPlants);
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
  const selectedFuel = elements.fuelSelect.value;
  const searchTerm = elements.searchInput.value.trim().toLowerCase();
  const minimumValue = parseInputNumber(elements.minimumInput.value);

  return state.plants.filter((plant) => {
    if (selectedState && plant.state !== selectedState) {
      return false;
    }
    if (selectedFuel && plant.primary_fuel_code !== selectedFuel) {
      return false;
    }
    if (searchTerm && !plant.searchText.includes(searchTerm)) {
      return false;
    }

    if (minimumValue !== null) {
      const metricValue = getMetricValue(plant, state.activeMetricKey);
      if (!Number.isFinite(metricValue) || metricValue < minimumValue) {
        return false;
      }
    }

    return true;
  });
}

function buildMetricStats(plants) {
  const values = [];
  let total = 0;
  let maxPlant = null;
  let maxValue = Number.NEGATIVE_INFINITY;

  for (const plant of plants) {
    const value = getMetricValue(plant, state.activeMetricKey);
    if (!Number.isFinite(value)) {
      continue;
    }
    total += value;
    values.push(value);
    if (value > maxValue) {
      maxValue = value;
      maxPlant = plant;
    }
  }

  return {
    values,
    countWithMetric: values.length,
    total,
    maxValue: Number.isFinite(maxValue) ? maxValue : null,
    maxPlant,
  };
}

function renderSummary(metricStats) {
  const metricDefinition = currentMetricDefinitions().find((item) => item.key === state.activeMetricKey);

  elements.visibleCount.textContent = integerFormatter.format(state.filteredPlants.length);
  elements.metricTotal.textContent = metricStats.countWithMetric
    ? formatMetric(metricStats.total)
    : "No data";
  elements.metricMax.textContent = metricStats.maxPlant
    ? `${metricStats.maxPlant.plant_name} (${formatMetric(metricStats.maxValue)})`
    : "No data";
  elements.metricName.textContent = metricDefinition?.label ?? state.activeMetricKey;
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

  const heatPoints = state.filteredPlants
    .map((plant) => {
      const value = getMetricValue(plant, state.activeMetricKey);
      if (!Number.isFinite(value) || value <= 0) {
        return null;
      }
      const weight = Math.max(0.08, Math.sqrt(value / maxValue));
      return [plant.latitude, plant.longitude, weight];
    })
    .filter(Boolean);

  if (!heatPoints.length) {
    return;
  }

  state.heatLayer = L.heatLayer(heatPoints, {
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
  state.markerByCode.clear();

  if (elements.viewSelect.value === "heat") {
    return;
  }

  const maxValue = metricStats.maxValue ?? 0;
  for (const plant of state.filteredPlants) {
    const value = getMetricValue(plant, state.activeMetricKey);
    const radius = markerRadius(value, maxValue);
    const fillColor = markerColor(plant, value, maxValue);
    const marker = L.circleMarker([plant.latitude, plant.longitude], {
      renderer: state.canvasRenderer,
      radius,
      weight: 0.8,
      color: "rgba(31, 26, 22, 0.38)",
      fillColor,
      fillOpacity: Number.isFinite(value) ? 0.82 : 0.46,
    });

    marker.on("click", () => {
      marker.bindPopup(buildPopupHtml(plant)).openPopup();
      focusPlant(plant, { flyTo: false });
    });

    if (plant.plant_code === state.activePlantCode) {
      marker.bindPopup(buildPopupHtml(plant)).openPopup();
    }

    state.pointLayer.addLayer(marker);
    state.markerByCode.set(plant.plant_code, marker);
  }
}

function renderResults(metricStats) {
  const orderedPlants = [...state.filteredPlants].sort((left, right) => {
    const leftValue = getMetricValue(left, state.activeMetricKey) ?? Number.NEGATIVE_INFINITY;
    const rightValue = getMetricValue(right, state.activeMetricKey) ?? Number.NEGATIVE_INFINITY;
    if (rightValue !== leftValue) {
      return rightValue - leftValue;
    }
    return left.plant_name.localeCompare(right.plant_name);
  });

  const fragment = document.createDocumentFragment();

  if (!orderedPlants.length) {
    const empty = document.createElement("div");
    empty.className = "microcopy";
    empty.textContent = "No plants match the current filters.";
    fragment.append(empty);
  } else {
    const header = document.createElement("div");
    header.className = "microcopy";
    header.textContent = `Showing ${Math.min(25, orderedPlants.length)} of ${integerFormatter.format(orderedPlants.length)} plants.`;
    fragment.append(header);

    for (const plant of orderedPlants.slice(0, 25)) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "result-button";
      if (plant.plant_code === state.activePlantCode) {
        button.classList.add("active");
      }

      const title = document.createElement("div");
      title.className = "result-title";
      title.textContent = plant.plant_name;

      const location = document.createElement("div");
      location.className = "result-subline";
      location.textContent = `${plant.state} | ${plant.county || "County unknown"} | ${plant.primary_fuel_code || "Fuel unknown"}`;

      const valueLine = document.createElement("div");
      valueLine.className = "result-subline";
      valueLine.textContent = `${metricLabel(state.activeMetricKey)}: ${displayMetricValue(plant, state.activeMetricKey)}`;

      button.append(title, location, valueLine);
      button.addEventListener("click", () => {
        focusPlant(plant, { flyTo: true });
      });
      fragment.append(button);
    }
  }

  elements.resultsList.replaceChildren(fragment);

  if (!metricStats.countWithMetric) {
    setStatus("Filtered plants loaded, but the active metric has no numeric values in this view.");
  } else if (state.uploadSummary) {
    setStatus(
      `${state.uploadSummary.filename}: matched ${integerFormatter.format(
        state.uploadSummary.joinedPlantCount,
      )} plants across ${state.uploadSummary.metricCount} uploaded metrics.`,
    );
  } else {
    setStatus(`Viewing ${integerFormatter.format(state.filteredPlants.length)} plants using base EIA-860 metrics.`);
  }
}

function renderDetail() {
  const plant = state.plants.find((item) => item.plant_code === state.activePlantCode);
  if (!plant) {
    elements.detailPanel.textContent = "Select a plant point or a result row to inspect plant-level values.";
    return;
  }

  const detail = document.createDocumentFragment();

  const title = document.createElement("div");
  const titleStrong = document.createElement("strong");
  titleStrong.textContent = plant.plant_name;
  title.append(titleStrong);

  const subtitle = document.createElement("div");
  subtitle.className = "microcopy";
  subtitle.textContent = `${plant.city || "City unknown"}, ${plant.state} | Plant code ${plant.plant_code}`;

  const grid = document.createElement("div");
  grid.className = "detail-grid";

  const rows = [
    ["Selected metric", displayMetricValue(plant, state.activeMetricKey)],
    ["Utility", plant.utility_name || "Unknown"],
    ["County", plant.county || "Unknown"],
    ["Primary fuel", plant.primary_fuel_code || "Unknown"],
    ["Technology", plant.primary_technology || "Unknown"],
    ["Balancing authority", plant.balancing_authority_name || "Unknown"],
    ["Latitude", formatCoordinate(plant.latitude)],
    ["Longitude", formatCoordinate(plant.longitude)],
  ];

  for (const definition of BASE_METRIC_DEFINITIONS) {
    rows.push([definition.label, displayMetricValue(plant, definition.key)]);
  }

  for (const definition of state.uploadedMetricDefinitions) {
    rows.push([definition.label, displayMetricValue(plant, definition.key)]);
  }

  for (const [label, value] of rows) {
    const row = document.createElement("div");
    row.className = "detail-row";

    const keyNode = document.createElement("span");
    keyNode.textContent = label;

    const valueNode = document.createElement("strong");
    valueNode.textContent = value;

    row.append(keyNode, valueNode);
    grid.append(row);
  }

  detail.append(title, subtitle, grid);
  elements.detailPanel.replaceChildren(detail);
}

function focusPlant(plant, options = {}) {
  state.activePlantCode = plant.plant_code;
  renderResults(buildMetricStats(state.filteredPlants));
  renderDetail();

  const marker = state.markerByCode.get(plant.plant_code);
  if (marker) {
    marker.bindPopup(buildPopupHtml(plant)).openPopup();
  }

  if (options.flyTo) {
    state.map.flyTo([plant.latitude, plant.longitude], Math.max(state.map.getZoom(), 7), {
      duration: 0.65,
    });
  }
}

function zoomToFiltered() {
  if (!state.filteredPlants.length) {
    return;
  }

  if (state.filteredPlants.length === 1) {
    const [plant] = state.filteredPlants;
    state.map.flyTo([plant.latitude, plant.longitude], 8, { duration: 0.65 });
    return;
  }

  const bounds = L.latLngBounds(state.filteredPlants.map((plant) => [plant.latitude, plant.longitude]));
  state.map.fitBounds(bounds, { padding: [28, 28] });
}

async function loadEmissionsFile(file) {
  try {
    const text = await file.text();
    const rows = parseCsv(text);
    if (rows.length < 2) {
      throw new Error("The uploaded file does not contain data rows.");
    }

    const rawHeaders = rows[0];
    const normalizedHeaders = rawHeaders.map(normalizeHeader);
    const keyIndex = findPlantCodeIndex(normalizedHeaders);
    if (keyIndex < 0) {
      throw new Error("Expected a plant code column such as plant_code or eia_plant_code.");
    }

    const numericIndexes = detectNumericColumns(rows.slice(1), normalizedHeaders, keyIndex);
    if (!numericIndexes.length) {
      throw new Error("No numeric emissions columns were detected in the uploaded file.");
    }

    const joinedMetrics = new Map();
    for (const row of rows.slice(1)) {
      if (!row.some((value) => value.trim())) {
        continue;
      }

      const plantCode = normalizePlantCode(row[keyIndex]);
      if (!plantCode) {
        continue;
      }

      const metricBucket = joinedMetrics.get(plantCode) ?? {};
      for (const index of numericIndexes) {
        const metricKey = normalizedHeaders[index];
        const value = parseInputNumber(row[index]);
        if (value === null) {
          continue;
        }
        metricBucket[metricKey] = (metricBucket[metricKey] ?? 0) + value;
      }
      joinedMetrics.set(plantCode, metricBucket);
    }

    state.uploadedMetricDefinitions = numericIndexes.map((index) => ({
      key: `${EMISSIONS_PREFIX}${normalizedHeaders[index]}`,
      label: guessMetricLabel(normalizedHeaders[index]),
      source: "upload",
      rawKey: normalizedHeaders[index],
    }));

    let joinedPlantCount = 0;
    for (const plant of state.plants) {
      const metrics = joinedMetrics.get(plant.plant_code) ?? {};
      plant.uploadedMetrics = metrics;
      if (Object.keys(metrics).length) {
        joinedPlantCount += 1;
      }
    }

    state.uploadSummary = {
      filename: file.name,
      joinedPlantCount,
      metricCount: state.uploadedMetricDefinitions.length,
    };
    elements.uploadSummary.textContent = `${file.name} joined ${integerFormatter.format(
      joinedPlantCount,
    )} plants and exposed ${state.uploadedMetricDefinitions.length} numeric metric columns.`;

    syncMetricOptions();
    refreshView();
  } catch (error) {
    console.error(error);
    setStatus(error.message || "Could not parse the uploaded emissions CSV.", "error");
  }
}

function clearUploadedMetrics() {
  for (const plant of state.plants) {
    plant.uploadedMetrics = {};
  }
  state.uploadedMetricDefinitions = [];
  state.uploadSummary = null;
  elements.uploadSummary.textContent =
    "Base plant asset loads from data/private/visualizer/plants_reference.json.";
  syncMetricOptions();
}

function getMetricValue(plant, metricKey) {
  if (!metricKey) {
    return null;
  }

  if (metricKey.startsWith(EMISSIONS_PREFIX)) {
    const rawKey = metricKey.slice(EMISSIONS_PREFIX.length);
    return toNumber(plant.uploadedMetrics[rawKey]);
  }

  return toNumber(plant.baseMetrics[metricKey]);
}

function displayMetricValue(plant, metricKey) {
  const value = getMetricValue(plant, metricKey);
  return Number.isFinite(value) ? formatMetric(value) : "No data";
}

function metricLabel(metricKey) {
  return currentMetricDefinitions().find((item) => item.key === metricKey)?.label ?? metricKey;
}

function markerRadius(value, maxValue) {
  if (!Number.isFinite(value) || maxValue <= 0) {
    return 4.2;
  }
  return 4 + Math.sqrt(value / maxValue) * 10;
}

function markerColor(plant, value, maxValue) {
  if (!Number.isFinite(value) || maxValue <= 0) {
    return FUEL_COLORS[plant.primary_fuel_code] ?? "#8d7b68";
  }
  const ratio = Math.max(0, Math.min(1, Math.sqrt(value / maxValue)));
  return interpolateColor("#fee08b", "#9e0142", ratio);
}

function buildPopupHtml(plant) {
  return [
    `<div class="popup-title">${escapeHtml(plant.plant_name)}</div>`,
    `<div class="popup-line">${escapeHtml(plant.utility_name || "Unknown utility")}</div>`,
    `<div class="popup-line">${escapeHtml(plant.city || "Unknown city")}, ${escapeHtml(plant.state)}</div>`,
    `<div class="popup-line">${escapeHtml(metricLabel(state.activeMetricKey))}: ${escapeHtml(
      displayMetricValue(plant, state.activeMetricKey),
    )}</div>`,
    `<div class="popup-line">Fuel: ${escapeHtml(plant.primary_fuel_code || "Unknown")}</div>`,
  ].join("");
}

function parseCsv(text) {
  const rows = [];
  let cell = "";
  let row = [];
  let insideQuotes = false;
  const normalizedText = text.replace(/^\uFEFF/, "");

  for (let index = 0; index < normalizedText.length; index += 1) {
    const character = normalizedText[index];

    if (insideQuotes) {
      if (character === '"') {
        if (normalizedText[index + 1] === '"') {
          cell += '"';
          index += 1;
        } else {
          insideQuotes = false;
        }
      } else {
        cell += character;
      }
      continue;
    }

    if (character === '"') {
      insideQuotes = true;
    } else if (character === ",") {
      row.push(cell);
      cell = "";
    } else if (character === "\n") {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else if (character !== "\r") {
      cell += character;
    }
  }

  if (cell.length || row.length) {
    row.push(cell);
    rows.push(row);
  }

  return rows.filter((currentRow) => currentRow.some((value) => value.trim().length));
}

function findPlantCodeIndex(headers) {
  const candidates = ["plant_code", "eia_plant_code", "eia860_plant_code", "plant_id"];
  return headers.findIndex((header) => candidates.includes(header));
}

function detectNumericColumns(rows, headers, keyIndex) {
  const skipHeaders = new Set([
    "plant_name",
    "utility_name",
    "state",
    "county",
    "city",
    "reporting_year",
    "year",
  ]);

  const numericIndexes = [];
  for (let index = 0; index < headers.length; index += 1) {
    if (index === keyIndex) {
      continue;
    }
    if (skipHeaders.has(headers[index])) {
      continue;
    }

    const hasNumericValue = rows.some((row) => parseInputNumber(row[index]) !== null);
    if (hasNumericValue) {
      numericIndexes.push(index);
    }
  }

  return numericIndexes;
}

function normalizeHeader(value) {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

function normalizePlantCode(value) {
  return value.trim().replace(/\.0+$/, "");
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
  if (value === null || value === undefined || value === "") {
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
  return numberFormatter.format(value);
}

function formatCoordinate(value) {
  return Number.isFinite(value) ? value.toFixed(4) : "No data";
}

function guessMetricLabel(rawKey) {
  return rawKey
    .split("_")
    .map((token) => {
      const uppercaseTokens = new Map([
        ["co2", "CO2"],
        ["co2e", "CO2e"],
        ["nox", "NOx"],
        ["so2", "SO2"],
        ["mw", "MW"],
        ["mwh", "MWh"],
        ["lb", "lb"],
        ["lbs", "lb"],
      ]);
      return uppercaseTokens.get(token) ?? token.charAt(0).toUpperCase() + token.slice(1);
    })
    .join(" ");
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
