const DATA_URL = "../../data/private/visualizer/plants_reference.json";
const EMISSIONS_PREFIX = "emissions:";
const DIRECT_MODE = "direct";
const OVERLAY_MODE = "overlay";

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

const BASE_METRIC_KEY_SET = new Set(BASE_METRIC_DEFINITIONS.map((definition) => definition.key));

const PREFERRED_UPLOADED_METRICS = [
  "radioisotopic_emissions_value",
  "co2_tons",
  "co2_mass_tons",
  "co2e_tons",
  "co2_equivalent_tons",
  "mercury_lb",
  "mercury_lbs",
  "mercury_emissions_value",
  "so2_tons",
  "so2_emissions_value",
  "nox_tons",
  "nox_emissions_value",
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

const KEY_HEADER_CANDIDATES = [
  "plant_code",
  "eia_plant_code",
  "eia860_plant_code",
  "plant_id",
  "eia_plant_id",
  "orispl",
  "oris_plant_code",
  "oris_plant",
];

const LAT_HEADER_HINTS = ["latitude", "lat", "plant_latitude", "y_coord", "y_coordinate"];
const LON_HEADER_HINTS = ["longitude", "lon", "lng", "long", "plant_longitude", "x_coord", "x_coordinate"];
const NAME_HEADER_HINTS = ["plant_name", "facility_name", "name", "station_name", "site_name", "plant"];
const UTILITY_HEADER_HINTS = ["utility_name", "owner_name", "company_name", "operator_name"];
const CITY_HEADER_HINTS = ["city", "plant_city", "municipality"];
const COUNTY_HEADER_HINTS = ["county", "county_name", "plant_county"];
const STATE_HEADER_HINTS = ["state", "state_code", "plant_state"];
const FUEL_HEADER_HINTS = ["primary_fuel_code", "fuel", "fuel_code", "primary_fuel"];

const NON_METRIC_HEADERS = new Set([
  "plant_code",
  "eia_plant_code",
  "eia860_plant_code",
  "plant_id",
  "eia_plant_id",
  "orispl",
  "oris_plant_code",
  "plant_name",
  "utility_name",
  "utility_id",
  "street_address",
  "address",
  "city",
  "county",
  "state",
  "state_code",
  "zip_code",
  "zip",
  "latitude",
  "longitude",
  "lat",
  "lon",
  "lng",
  "long",
  "coordinate_status",
  "reporting_year",
  "year",
  "source_dataset",
  "source_sheets",
  "emissions_profile_status",
  "status_mix",
  "status",
]);

const state = {
  basePlants: [],
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
  importAnalysis: null,
  importConfig: null,
};

const numberFormatter = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });
const integerFormatter = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

const elements = {
  emissionsFile: document.getElementById("emissions-file"),
  clearEmissions: document.getElementById("clear-emissions"),
  uploadSummary: document.getElementById("upload-summary"),
  importWizard: document.getElementById("import-wizard"),
  wizardOverview: document.getElementById("wizard-overview"),
  wizardAlert: document.getElementById("wizard-alert"),
  wizardMode: document.getElementById("wizard-mode"),
  wizardKey: document.getElementById("wizard-key"),
  wizardLat: document.getElementById("wizard-lat"),
  wizardLon: document.getElementById("wizard-lon"),
  wizardName: document.getElementById("wizard-name"),
  wizardState: document.getElementById("wizard-state"),
  wizardFuel: document.getElementById("wizard-fuel"),
  wizardMetric: document.getElementById("wizard-metric"),
  wizardRowCount: document.getElementById("wizard-row-count"),
  wizardMetricCount: document.getElementById("wizard-metric-count"),
  wizardCoordinateCount: document.getElementById("wizard-coordinate-count"),
  wizardMatchCount: document.getElementById("wizard-match-count"),
  wizardCoverage: document.getElementById("wizard-coverage"),
  applyImport: document.getElementById("apply-import"),
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
    state.basePlants = payload.plants.map(hydratePlant);
    resetToBasePlants();
    populateFilters();
    syncMetricOptions();
    setStatus(`Loaded ${integerFormatter.format(state.basePlants.length)} plant coordinates.`);
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
    refreshView({ fitBounds: true });
  });

  for (const control of [
    elements.wizardMode,
    elements.wizardKey,
    elements.wizardLat,
    elements.wizardLon,
    elements.wizardName,
    elements.wizardState,
    elements.wizardFuel,
    elements.wizardMetric,
  ]) {
    control.addEventListener("change", () => {
      handleWizardChange();
    });
  }

  elements.applyImport.addEventListener("click", () => {
    applyImportFromWizard({ fitBounds: true });
  });
}

function hydratePlant(plant) {
  const plantCode = normalizePlantCode(plant.plant_code);
  const baseMetrics = {};
  for (const definition of BASE_METRIC_DEFINITIONS) {
    baseMetrics[definition.key] = toNumber(plant[definition.key]);
  }

  return {
    ...plant,
    plant_code: plantCode,
    latitude: Number(plant.latitude),
    longitude: Number(plant.longitude),
    baseMetrics,
    uploadedMetrics: {},
    metricMetadata: {},
    searchText: buildSearchText({
      ...plant,
      plant_code: plantCode,
    }),
  };
}

function clonePlant(plant) {
  return {
    ...plant,
    baseMetrics: { ...plant.baseMetrics },
    uploadedMetrics: { ...plant.uploadedMetrics },
    metricMetadata: { ...plant.metricMetadata },
  };
}

function clonePlantCollection(plants) {
  return plants.map(clonePlant);
}

function resetToBasePlants() {
  state.plants = clonePlantCollection(state.basePlants);
  state.uploadedMetricDefinitions = [];
  state.activePlantCode = "";
}

function buildSearchText(plant) {
  return [
    plant.plant_code,
    plant.plant_name,
    plant.utility_name,
    plant.county,
    plant.city,
    plant.state,
    plant.primary_fuel_code,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function populateFilters() {
  const previousState = elements.stateSelect.value;
  const previousFuel = elements.fuelSelect.value;
  const states = [...new Set(state.plants.map((plant) => plant.state).filter(Boolean))].sort();
  const fuels = [...new Set(state.plants.map((plant) => plant.primary_fuel_code).filter(Boolean))].sort();

  replaceSelectOptions(elements.stateSelect, states, "All states");
  replaceSelectOptions(elements.fuelSelect, fuels, "All fuels");

  if (states.includes(previousState)) {
    elements.stateSelect.value = previousState;
  }

  if (fuels.includes(previousFuel)) {
    elements.fuelSelect.value = previousFuel;
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

function currentMetricDefinitions() {
  const uniqueDefinitions = [];
  const seen = new Set();

  for (const definition of [...BASE_METRIC_DEFINITIONS, ...state.uploadedMetricDefinitions]) {
    if (seen.has(definition.key)) {
      continue;
    }
    seen.add(definition.key);
    uniqueDefinitions.push(definition);
  }

  return uniqueDefinitions;
}

function syncMetricOptions(preferredOverride = null) {
  const definitions = currentMetricDefinitions();
  const previousValue = state.activeMetricKey;

  let selectedValue = definitions.some((item) => item.key === previousValue) ? previousValue : null;
  if (preferredOverride && definitions.some((item) => item.key === preferredOverride)) {
    selectedValue = preferredOverride;
  }
  if (!selectedValue) {
    selectedValue = preferredMetricKey(definitions);
  }

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
    const uploadedMatch = definitions.find((item) => item.key === `${EMISSIONS_PREFIX}${preferred}`);
    if (uploadedMatch) {
      return uploadedMatch.key;
    }

    const baseMatch = definitions.find((item) => item.key === preferred);
    if (baseMatch) {
      return baseMatch.key;
    }
  }

  return definitions[0]?.key ?? BASE_METRIC_DEFINITIONS[0].key;
}

function refreshView(options = {}) {
  state.filteredPlants = applyFilters();

  if (!state.filteredPlants.some((plant) => plant.plant_code === state.activePlantCode)) {
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
    if (!Number.isFinite(plant.latitude) || !Number.isFinite(plant.longitude)) {
      return false;
    }
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
  let positiveCount = 0;

  for (const plant of plants) {
    const value = getMetricValue(plant, state.activeMetricKey);
    if (!Number.isFinite(value)) {
      continue;
    }

    total += value;
    values.push(value);
    if (value > 0) {
      positiveCount += 1;
    }
    if (value > maxValue) {
      maxValue = value;
      maxPlant = plant;
    }
  }

  return {
    values,
    countWithMetric: values.length,
    positiveCount,
    total,
    maxValue: Number.isFinite(maxValue) ? maxValue : null,
    maxPlant,
  };
}

function renderSummary(metricStats) {
  const metricDefinition = currentMetricDefinitions().find((item) => item.key === state.activeMetricKey);

  elements.visibleCount.textContent = integerFormatter.format(state.filteredPlants.length);
  elements.metricTotal.textContent = metricStats.countWithMetric ? formatMetric(metricStats.total) : "No data";
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
    return (left.plant_name || "").localeCompare(right.plant_name || "");
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
      title.textContent = plant.plant_name || `Plant ${plant.plant_code}`;

      const location = document.createElement("div");
      location.className = "result-subline";
      location.textContent = `${plant.state || "State unknown"} | ${plant.county || "County unknown"} | ${plant.primary_fuel_code || "Fuel unknown"}`;

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

  if (!state.filteredPlants.length) {
    setStatus("No plants match the current filters.");
    return;
  }

  if (!metricStats.countWithMetric) {
    setStatus("Filtered plants loaded, but the active metric has no numeric values in this view.");
    return;
  }

  if (elements.viewSelect.value !== "points" && metricStats.positiveCount === 0) {
    setStatus("The active metric has numeric values, but none are above zero, so the heatmap is empty.");
    return;
  }

  if (state.uploadSummary) {
    setStatus(state.uploadSummary.statusMessage);
    return;
  }

  setStatus(`Viewing ${integerFormatter.format(state.filteredPlants.length)} plants using base EIA-860 metrics.`);
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
  titleStrong.textContent = plant.plant_name || `Plant ${plant.plant_code}`;
  title.append(titleStrong);

  const subtitle = document.createElement("div");
  subtitle.className = "microcopy";
  subtitle.textContent = `${plant.city || "City unknown"}, ${plant.state || "State unknown"} | Plant code ${plant.plant_code}`;

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

  const activeMetricMetadata = getMetricMetadata(plant, state.activeMetricKey);
  if (activeMetricMetadata?.unit) {
    rows.splice(1, 0, ["Metric unit", activeMetricMetadata.unit]);
  }
  if (activeMetricMetadata?.basis) {
    rows.splice(2, 0, ["Metric basis", activeMetricMetadata.basis]);
  }
  if (activeMetricMetadata?.source) {
    rows.splice(3, 0, ["Metric source", activeMetricMetadata.source]);
  }
  if (activeMetricMetadata?.reportingYear) {
    rows.splice(4, 0, ["Metric year", activeMetricMetadata.reportingYear]);
  }

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
    const { rows, delimiter } = parseDelimitedText(text);
    if (rows.length < 2) {
      throw new Error("The uploaded file does not contain data rows.");
    }

    state.importAnalysis = analyzeUploadedRows(file.name, rows, delimiter);
    state.importConfig = { ...state.importAnalysis.recommendedConfig };
    renderImportWizard();
    applyImportFromWizard({ fitBounds: true });
  } catch (error) {
    console.error(error);
    setStatus(error.message || "Could not parse the uploaded emissions CSV.", "error");
  }
}

function renderImportWizard() {
  const analysis = state.importAnalysis;
  if (!analysis) {
    elements.importWizard.hidden = true;
    return;
  }

  elements.importWizard.hidden = false;
  elements.wizardOverview.textContent =
    `${analysis.fileName} • ${integerFormatter.format(analysis.rowCount)} rows • ${analysis.columnOptions.length} columns • ` +
    `${analysis.delimiterLabel}`;

  populateWizardModeSelect(analysis);
  populateWizardColumnSelect(elements.wizardKey, analysis.columnOptions, state.importConfig?.keyIndex, {
    allowBlank: true,
    blankLabel: "None",
  });
  populateWizardColumnSelect(elements.wizardLat, analysis.columnOptions, state.importConfig?.latIndex, {
    allowBlank: true,
    blankLabel: "None",
  });
  populateWizardColumnSelect(elements.wizardLon, analysis.columnOptions, state.importConfig?.lonIndex, {
    allowBlank: true,
    blankLabel: "None",
  });
  populateWizardColumnSelect(elements.wizardName, analysis.columnOptions, state.importConfig?.nameIndex, {
    allowBlank: true,
    blankLabel: "None",
  });
  populateWizardColumnSelect(elements.wizardState, analysis.columnOptions, state.importConfig?.stateIndex, {
    allowBlank: true,
    blankLabel: "None",
  });
  populateWizardColumnSelect(elements.wizardFuel, analysis.columnOptions, state.importConfig?.fuelIndex, {
    allowBlank: true,
    blankLabel: "None",
  });

  elements.wizardMetric.replaceChildren();
  for (const candidate of analysis.metricCandidates) {
    const option = document.createElement("option");
    option.value = candidate.normalizedHeader;
    option.textContent = `${candidate.label} (${integerFormatter.format(candidate.valueCount)} rows)`;
    elements.wizardMetric.append(option);
  }
  if (analysis.metricCandidates.length) {
    elements.wizardMetric.value = state.importConfig?.metricKey ?? analysis.metricCandidates[0].normalizedHeader;
  }

  renderWizardPreview();
}

function populateWizardModeSelect(analysis) {
  elements.wizardMode.replaceChildren();

  const options = [];
  if (analysis.capabilities.canDirect) {
    options.push([DIRECT_MODE, "Use uploaded coordinates + metrics"]);
  }
  if (analysis.capabilities.canOverlay) {
    options.push([OVERLAY_MODE, "Join metrics onto base coordinates"]);
  }

  if (!options.length) {
    options.push([DIRECT_MODE, "Use uploaded coordinates + metrics"]);
  }

  for (const [value, label] of options) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    elements.wizardMode.append(option);
  }

  const configuredMode = state.importConfig?.mode;
  if (configuredMode && options.some(([value]) => value === configuredMode)) {
    elements.wizardMode.value = configuredMode;
    return;
  }

  elements.wizardMode.value = options[0][0];
}

function populateWizardColumnSelect(select, columnOptions, selectedIndex, options = {}) {
  const { allowBlank = false, blankLabel = "None" } = options;
  select.replaceChildren();

  if (allowBlank) {
    const blankOption = document.createElement("option");
    blankOption.value = "";
    blankOption.textContent = blankLabel;
    select.append(blankOption);
  }

  for (const column of columnOptions) {
    const option = document.createElement("option");
    option.value = String(column.index);
    option.textContent = column.label;
    select.append(option);
  }

  if (selectedIndex === null || selectedIndex === undefined) {
    if (allowBlank) {
      select.value = "";
    }
    return;
  }

  const selectedValue = String(selectedIndex);
  if ([...select.options].some((option) => option.value === selectedValue)) {
    select.value = selectedValue;
  } else if (allowBlank) {
    select.value = "";
  }
}

function handleWizardChange() {
  if (!state.importAnalysis) {
    return;
  }

  state.importConfig = collectWizardConfig();
  renderWizardPreview();
}

function collectWizardConfig() {
  return {
    utilityIndex: state.importConfig?.utilityIndex ?? state.importAnalysis?.recommendedConfig.utilityIndex ?? null,
    cityIndex: state.importConfig?.cityIndex ?? state.importAnalysis?.recommendedConfig.cityIndex ?? null,
    countyIndex: state.importConfig?.countyIndex ?? state.importAnalysis?.recommendedConfig.countyIndex ?? null,
    mode: elements.wizardMode.value || DIRECT_MODE,
    keyIndex: selectValueToIndex(elements.wizardKey.value),
    latIndex: selectValueToIndex(elements.wizardLat.value),
    lonIndex: selectValueToIndex(elements.wizardLon.value),
    nameIndex: selectValueToIndex(elements.wizardName.value),
    stateIndex: selectValueToIndex(elements.wizardState.value),
    fuelIndex: selectValueToIndex(elements.wizardFuel.value),
    metricKey: elements.wizardMetric.value || state.importAnalysis?.metricCandidates[0]?.normalizedHeader || "",
  };
}

function renderWizardPreview(alert = null) {
  const analysis = state.importAnalysis;
  if (!analysis) {
    return;
  }

  const config = collectWizardConfig();
  const preview = buildImportPreview(analysis, config);

  elements.wizardRowCount.textContent = integerFormatter.format(analysis.rowCount);
  elements.wizardMetricCount.textContent = integerFormatter.format(analysis.metricCandidates.length);
  elements.wizardCoordinateCount.textContent = integerFormatter.format(preview.coordinateRows);
  elements.wizardMatchCount.textContent = integerFormatter.format(preview.matchCount);
  elements.wizardCoverage.textContent = preview.message;

  if (alert) {
    renderWizardAlert(alert.message, alert.tone);
    return;
  }

  if (!preview.canApply) {
    renderWizardAlert(preview.message, "error");
  } else if (preview.selectedMetric && preview.selectedMetric.valueCount > 0) {
    renderWizardAlert(
      `${preview.selectedMetric.label} has ${integerFormatter.format(preview.selectedMetric.valueCount)} numeric rows` +
        `${preview.selectedMetric.positiveCount ? ` and ${integerFormatter.format(preview.selectedMetric.positiveCount)} positive values.` : "."}`,
      "success",
    );
  } else {
    renderWizardAlert("We detected the file and are ready to apply it.", "success");
  }
}

function renderWizardAlert(message, tone) {
  elements.wizardAlert.hidden = !message;
  elements.wizardAlert.textContent = message || "";
  elements.wizardAlert.dataset.tone = tone || "info";
}

function applyImportFromWizard(options = {}) {
  const analysis = state.importAnalysis;
  if (!analysis) {
    return;
  }

  const config = collectWizardConfig();
  const preview = buildImportPreview(analysis, config);
  if (!preview.canApply) {
    renderWizardPreview({ message: preview.message, tone: "error" });
    setStatus(preview.message, "error");
    return;
  }

  const result =
    config.mode === OVERLAY_MODE ? applyOverlayImport(analysis, config, preview) : applyDirectImport(analysis, config, preview);

  state.importConfig = config;
  state.activePlantCode = "";
  populateFilters();
  syncMetricOptions(result.preferredMetricKey);
  refreshView({ fitBounds: options.fitBounds ?? false });
  renderWizardPreview({ message: result.summaryMessage, tone: "success" });
}

function analyzeUploadedRows(fileName, rows, delimiter) {
  const rawHeaders = rows[0].map((value) => value.trim());
  const normalizedHeaders = rawHeaders.map(normalizeHeader);
  const dataRows = rows.slice(1).filter((row) => row.some((value) => String(value).trim().length));
  const basePlantCodes = new Set(state.basePlants.map((plant) => normalizePlantCode(plant.plant_code)).filter(Boolean));

  const columnOptions = rawHeaders.map((rawHeader, index) => {
    const normalizedHeader = normalizedHeaders[index];
    const nonEmptyCount = dataRows.filter((row) => String(row[index] ?? "").trim()).length;
    const numericCount = dataRows.filter((row) => parseInputNumber(row[index]) !== null).length;
    return {
      index,
      rawHeader,
      normalizedHeader,
      nonEmptyCount,
      numericCount,
      label: rawHeader || `Column ${index + 1}`,
    };
  });

  const keyIndex = chooseBestKeyIndex(normalizedHeaders, dataRows, basePlantCodes);
  const latIndex = chooseCoordinateIndex(normalizedHeaders, dataRows, LAT_HEADER_HINTS, -90, 90);
  const lonIndex = chooseCoordinateIndex(normalizedHeaders, dataRows, LON_HEADER_HINTS, -180, 180);
  const nameIndex = chooseHeaderIndex(normalizedHeaders, NAME_HEADER_HINTS);
  const stateIndex = chooseHeaderIndex(normalizedHeaders, STATE_HEADER_HINTS);
  const fuelIndex = chooseHeaderIndex(normalizedHeaders, FUEL_HEADER_HINTS);

  const metricCandidates = detectMetricColumns(dataRows, rawHeaders, normalizedHeaders);
  if (!metricCandidates.length) {
    throw new Error("No numeric metric columns were detected in the uploaded file.");
  }

  const coordinateRows = countCoordinateRows(dataRows, latIndex, lonIndex);
  const matchCount = countMatchedBaseRows(dataRows, keyIndex, basePlantCodes);

  return {
    fileName,
    delimiter,
    delimiterLabel: describeDelimiter(delimiter),
    rowCount: dataRows.length,
    rawHeaders,
    normalizedHeaders,
    dataRows,
    columnOptions,
    metricCandidates,
    capabilities: {
      canDirect: coordinateRows > 0,
      canOverlay: matchCount > 0,
    },
    recommendedConfig: {
      mode: coordinateRows > 0 ? DIRECT_MODE : OVERLAY_MODE,
      keyIndex,
      latIndex,
      lonIndex,
      nameIndex,
      utilityIndex: chooseHeaderIndex(normalizedHeaders, UTILITY_HEADER_HINTS),
      cityIndex: chooseHeaderIndex(normalizedHeaders, CITY_HEADER_HINTS),
      countyIndex: chooseHeaderIndex(normalizedHeaders, COUNTY_HEADER_HINTS),
      stateIndex,
      fuelIndex,
      metricKey: chooseRecommendedMetricKey(metricCandidates),
    },
  };
}

function buildImportPreview(analysis, config) {
  const basePlantCodes = new Set(state.basePlants.map((plant) => normalizePlantCode(plant.plant_code)).filter(Boolean));
  const coordinateRows = countCoordinateRows(analysis.dataRows, config.latIndex, config.lonIndex);
  const matchCount = countMatchedBaseRows(analysis.dataRows, config.keyIndex, basePlantCodes);
  const selectedMetric =
    analysis.metricCandidates.find((candidate) => candidate.normalizedHeader === config.metricKey) ??
    analysis.metricCandidates[0] ??
    null;

  if (config.mode === OVERLAY_MODE) {
    if (config.keyIndex === null) {
      return {
        canApply: false,
        coordinateRows,
        matchCount,
        selectedMetric,
        message: "Pick a plant code column before joining metrics onto the base plant asset.",
      };
    }

    if (matchCount <= 0) {
      return {
        canApply: false,
        coordinateRows,
        matchCount,
        selectedMetric,
        message: "That plant code column does not match any loaded base plants yet. Try a different ID column or switch to uploaded coordinates.",
      };
    }

    return {
      canApply: true,
      coordinateRows,
      matchCount,
      selectedMetric,
      message:
        `Join mode will match ${integerFormatter.format(matchCount)} uploaded rows onto the base plant coordinates` +
        `${selectedMetric ? ` and start on ${selectedMetric.label}.` : "."}`,
    };
  }

  if (config.latIndex === null || config.lonIndex === null) {
    return {
      canApply: false,
      coordinateRows,
      matchCount,
      selectedMetric,
      message: "Pick both latitude and longitude columns to use the uploaded file as its own mapped dataset.",
    };
  }

  if (coordinateRows <= 0) {
    return {
      canApply: false,
      coordinateRows,
      matchCount,
      selectedMetric,
      message: "The selected coordinate columns do not contain any valid lat/long rows.",
    };
  }

  return {
    canApply: true,
    coordinateRows,
    matchCount,
    selectedMetric,
    message:
      `Direct mode will map ${integerFormatter.format(coordinateRows)} uploaded coordinate rows` +
      `${selectedMetric ? ` and start on ${selectedMetric.label}.` : "."}`,
  };
}

function applyOverlayImport(analysis, config, preview) {
  const joinedMetrics = new Map();
  const joinedMetadata = new Map();
  const metricDefinitions = buildUploadedMetricDefinitions(analysis.metricCandidates);
  const plants = clonePlantCollection(state.basePlants);

  for (const row of analysis.dataRows) {
    const plantCode = normalizePlantCode(row[config.keyIndex]);
    if (!plantCode) {
      continue;
    }

    const metricBucket = joinedMetrics.get(plantCode) ?? {};
    const metadataBucket = joinedMetadata.get(plantCode) ?? {};

    for (const candidate of analysis.metricCandidates) {
      const value = parseInputNumber(row[candidate.index]);
      if (value === null) {
        continue;
      }

      metricBucket[candidate.normalizedHeader] = (metricBucket[candidate.normalizedHeader] ?? 0) + value;
      const metricKey = `${EMISSIONS_PREFIX}${candidate.normalizedHeader}`;
      metadataBucket[metricKey] = metadataBucket[metricKey] ?? extractMetricMetadata(row, candidate);
    }

    joinedMetrics.set(plantCode, metricBucket);
    joinedMetadata.set(plantCode, metadataBucket);
  }

  let joinedPlantCount = 0;
  for (const plant of plants) {
    const plantCode = normalizePlantCode(plant.plant_code);
    plant.uploadedMetrics = joinedMetrics.get(plantCode) ?? {};
    plant.metricMetadata = joinedMetadata.get(plantCode) ?? {};
    if (Object.keys(plant.uploadedMetrics).length) {
      joinedPlantCount += 1;
    }
  }

  state.plants = plants;
  state.uploadedMetricDefinitions = metricDefinitions;
  state.uploadSummary = {
    filename: analysis.fileName,
    mode: OVERLAY_MODE,
    joinedPlantCount,
    metricCount: metricDefinitions.length,
    statusMessage:
      `${analysis.fileName}: joined ${integerFormatter.format(joinedPlantCount)} plants using ` +
      `${integerFormatter.format(metricDefinitions.length)} uploaded metric columns.`,
  };

  elements.uploadSummary.textContent =
    `${analysis.fileName} is running in join mode and matched ${integerFormatter.format(joinedPlantCount)} base plants ` +
    `across ${metricDefinitions.length} numeric columns.`;

  return {
    preferredMetricKey: config.metricKey ? `${EMISSIONS_PREFIX}${config.metricKey}` : preferredMetricKey(currentMetricDefinitions()),
    summaryMessage:
      `${analysis.fileName} joined ${integerFormatter.format(joinedPlantCount)} plants. ` +
      `${preview.selectedMetric ? `${preview.selectedMetric.label} is ready to map.` : "Uploaded metrics are ready to map."}`,
  };
}

function applyDirectImport(analysis, config, preview) {
  const grouped = new Map();
  const basePlantByCode = new Map(state.basePlants.map((plant) => [normalizePlantCode(plant.plant_code), plant]));

  for (let rowIndex = 0; rowIndex < analysis.dataRows.length; rowIndex += 1) {
    const row = analysis.dataRows[rowIndex];
    const latitude = parseInputNumber(row[config.latIndex]);
    const longitude = parseInputNumber(row[config.lonIndex]);
    if (!isFiniteCoordinate(latitude, -90, 90) || !isFiniteCoordinate(longitude, -180, 180)) {
      continue;
    }

    let plantCode = normalizePlantCode(config.keyIndex === null ? "" : row[config.keyIndex]);
    if (!plantCode) {
      plantCode = `row-${rowIndex + 1}`;
    }

    const basePlant = basePlantByCode.get(plantCode);
    const existing = grouped.get(plantCode);
    const plant = existing ?? {
      plant_code: plantCode,
      plant_name: readCell(row, config.nameIndex) || basePlant?.plant_name || `Plant ${plantCode}`,
      utility_id: "",
      utility_name: readCell(row, config.utilityIndex) || basePlant?.utility_name || "",
      city: readCell(row, config.cityIndex) || basePlant?.city || "",
      county: readCell(row, config.countyIndex) || basePlant?.county || "",
      state: readCell(row, config.stateIndex) || basePlant?.state || "",
      zip_code: "",
      latitude,
      longitude,
      coordinate_status: "uploaded",
      nerc_region: "",
      balancing_authority_code: "",
      balancing_authority_name: basePlant?.balancing_authority_name || "",
      primary_fuel_code: readCell(row, config.fuelIndex) || basePlant?.primary_fuel_code || "",
      primary_technology: basePlant?.primary_technology || "",
      baseMetrics: {},
      uploadedMetrics: {},
      metricMetadata: {},
      _coordinateCount: 0,
    };

    plant.latitude += existing ? latitude : 0;
    plant.longitude += existing ? longitude : 0;
    plant._coordinateCount += 1;

    for (const candidate of analysis.metricCandidates) {
      const value = parseInputNumber(row[candidate.index]);
      if (value === null) {
        continue;
      }

      if (BASE_METRIC_KEY_SET.has(candidate.normalizedHeader)) {
        plant.baseMetrics[candidate.normalizedHeader] = (plant.baseMetrics[candidate.normalizedHeader] ?? 0) + value;
        plant.metricMetadata[candidate.normalizedHeader] =
          plant.metricMetadata[candidate.normalizedHeader] ?? extractMetricMetadata(row, candidate);
      } else {
        plant.uploadedMetrics[candidate.normalizedHeader] = (plant.uploadedMetrics[candidate.normalizedHeader] ?? 0) + value;
        plant.metricMetadata[`${EMISSIONS_PREFIX}${candidate.normalizedHeader}`] =
          plant.metricMetadata[`${EMISSIONS_PREFIX}${candidate.normalizedHeader}`] ?? extractMetricMetadata(row, candidate);
      }
    }

    grouped.set(plantCode, plant);
  }

  const plants = [...grouped.values()].map((plant) => {
    const coordinateCount = Math.max(1, plant._coordinateCount);
    const normalizedPlant = {
      ...plant,
      latitude: plant.latitude / coordinateCount,
      longitude: plant.longitude / coordinateCount,
      uploadedMetrics: { ...plant.uploadedMetrics },
      metricMetadata: { ...plant.metricMetadata },
    };

    delete normalizedPlant._coordinateCount;
    normalizedPlant.searchText = buildSearchText(normalizedPlant);
    return normalizedPlant;
  });

  state.plants = plants;
  state.uploadedMetricDefinitions = buildUploadedMetricDefinitions(analysis.metricCandidates).filter(
    (definition) => !BASE_METRIC_KEY_SET.has(definition.rawKey),
  );
  state.uploadSummary = {
    filename: analysis.fileName,
    mode: DIRECT_MODE,
    joinedPlantCount: plants.length,
    metricCount: analysis.metricCandidates.length,
    statusMessage:
      `${analysis.fileName}: mapped ${integerFormatter.format(plants.length)} uploaded rows directly` +
      ` using ${integerFormatter.format(analysis.metricCandidates.length)} numeric metric columns.`,
  };

  elements.uploadSummary.textContent =
    `${analysis.fileName} is running in direct mode with ${integerFormatter.format(plants.length)} mapped plant rows ` +
    `and ${analysis.metricCandidates.length} numeric columns ready to analyze.`;

  return {
    preferredMetricKey: BASE_METRIC_KEY_SET.has(config.metricKey) ? config.metricKey : `${EMISSIONS_PREFIX}${config.metricKey}`,
    summaryMessage:
      `${analysis.fileName} mapped ${integerFormatter.format(plants.length)} rows directly from the uploaded coordinates. ` +
      `${preview.selectedMetric ? `${preview.selectedMetric.label} is ready to map.` : "Uploaded metrics are ready to map."}`,
  };
}

function buildUploadedMetricDefinitions(metricCandidates) {
  return metricCandidates.map((candidate) => ({
    key: `${EMISSIONS_PREFIX}${candidate.normalizedHeader}`,
    label: `Imported · ${candidate.label}`,
    source: "upload",
    rawKey: candidate.normalizedHeader,
  }));
}

function clearUploadedMetrics() {
  resetToBasePlants();
  state.uploadSummary = null;
  state.importAnalysis = null;
  state.importConfig = null;
  elements.importWizard.hidden = true;
  elements.uploadSummary.textContent =
    "Base plant asset loads from data/private/visualizer/plants_reference.json.";
  populateFilters();
  syncMetricOptions(BASE_METRIC_DEFINITIONS[0].key);
  setStatus(`Loaded ${integerFormatter.format(state.basePlants.length)} plant coordinates.`);
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

function getMetricMetadata(plant, metricKey) {
  return plant.metricMetadata?.[metricKey] ?? null;
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
    `<div class="popup-title">${escapeHtml(plant.plant_name || `Plant ${plant.plant_code}`)}</div>`,
    `<div class="popup-line">${escapeHtml(plant.utility_name || "Unknown utility")}</div>`,
    `<div class="popup-line">${escapeHtml(plant.city || "Unknown city")}, ${escapeHtml(plant.state || "Unknown state")}</div>`,
    `<div class="popup-line">${escapeHtml(metricLabel(state.activeMetricKey))}: ${escapeHtml(
      displayMetricValue(plant, state.activeMetricKey),
    )}</div>`,
    `<div class="popup-line">Fuel: ${escapeHtml(plant.primary_fuel_code || "Unknown")}</div>`,
  ].join("");
}

function parseDelimitedText(text) {
  const normalizedText = text.replace(/^\uFEFF/, "");
  const delimiter = detectDelimiter(normalizedText);
  const rows = [];
  let cell = "";
  let row = [];
  let insideQuotes = false;

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
    } else if (character === delimiter) {
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

  return {
    rows: rows.filter((currentRow) => currentRow.some((value) => String(value).trim().length)),
    delimiter,
  };
}

function detectDelimiter(text) {
  const sampleLines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .slice(0, 5);

  const candidates = [",", "\t", ";", "|"];
  let bestDelimiter = ",";
  let bestScore = -1;

  for (const candidate of candidates) {
    const score = sampleLines.reduce((total, line) => total + countCharacter(line, candidate), 0);
    if (score > bestScore) {
      bestScore = score;
      bestDelimiter = candidate;
    }
  }

  return bestDelimiter;
}

function countCharacter(text, character) {
  let count = 0;
  for (const value of text) {
    if (value === character) {
      count += 1;
    }
  }
  return count;
}

function describeDelimiter(delimiter) {
  switch (delimiter) {
    case "\t":
      return "tab-delimited";
    case ";":
      return "semicolon-delimited";
    case "|":
      return "pipe-delimited";
    default:
      return "comma-delimited";
  }
}

function chooseBestKeyIndex(headers, rows, basePlantCodes) {
  const candidateIndexes = [];

  for (let index = 0; index < headers.length; index += 1) {
    const header = headers[index];
    if (KEY_HEADER_CANDIDATES.includes(header) || header.includes("plant") || header.includes("oris")) {
      candidateIndexes.push(index);
    }
  }

  let bestIndex = null;
  let bestMatchCount = -1;

  for (const index of candidateIndexes) {
    const matchCount = countMatchedBaseRows(rows, index, basePlantCodes);
    if (matchCount > bestMatchCount) {
      bestMatchCount = matchCount;
      bestIndex = index;
    }
  }

  return bestIndex;
}

function chooseCoordinateIndex(headers, rows, headerHints, minimum, maximum) {
  const candidateIndexes = [];
  for (let index = 0; index < headers.length; index += 1) {
    const header = headers[index];
    if (headerHints.includes(header) || headerHints.some((hint) => header.includes(hint))) {
      candidateIndexes.push(index);
    }
  }

  let bestIndex = null;
  let bestCount = -1;
  for (const index of candidateIndexes) {
    let count = 0;
    for (const row of rows) {
      const value = parseInputNumber(row[index]);
      if (isFiniteCoordinate(value, minimum, maximum)) {
        count += 1;
      }
    }
    if (count > bestCount) {
      bestCount = count;
      bestIndex = index;
    }
  }

  return bestIndex;
}

function chooseHeaderIndex(headers, candidates) {
  const exactMatch = headers.findIndex((header) => candidates.includes(header));
  if (exactMatch >= 0) {
    return exactMatch;
  }

  return headers.findIndex((header) => candidates.some((candidate) => header.includes(candidate)));
}

function detectMetricColumns(rows, rawHeaders, normalizedHeaders) {
  const candidates = [];

  for (let index = 0; index < normalizedHeaders.length; index += 1) {
    const header = normalizedHeaders[index];
    if (!header) {
      continue;
    }
    if (NON_METRIC_HEADERS.has(header)) {
      continue;
    }
    if (header.endsWith("_unit") || header.endsWith("_basis") || header.endsWith("_source") || header.endsWith("_year")) {
      continue;
    }
    if (header.endsWith("_reporting_year") || header.endsWith("_id") || header.endsWith("_ids")) {
      continue;
    }

    let valueCount = 0;
    let positiveCount = 0;
    for (const row of rows) {
      const value = parseInputNumber(row[index]);
      if (value === null) {
        continue;
      }
      valueCount += 1;
      if (value > 0) {
        positiveCount += 1;
      }
    }

    if (!valueCount) {
      continue;
    }

    candidates.push({
      index,
      rawHeader: rawHeaders[index],
      normalizedHeader: header,
      label: guessMetricLabel(header),
      valueCount,
      positiveCount,
      unitIndex: findAssociatedColumnIndex(normalizedHeaders, header, "unit"),
      basisIndex: findAssociatedColumnIndex(normalizedHeaders, header, "basis"),
      sourceIndex: findAssociatedColumnIndex(normalizedHeaders, header, "source"),
      reportingYearIndex: findAssociatedColumnIndex(normalizedHeaders, header, "reporting_year"),
      priority: metricPriority(header, valueCount, positiveCount),
    });
  }

  return candidates.sort((left, right) => {
    if (right.priority !== left.priority) {
      return right.priority - left.priority;
    }
    if (right.valueCount !== left.valueCount) {
      return right.valueCount - left.valueCount;
    }
    return left.label.localeCompare(right.label);
  });
}

function findAssociatedColumnIndex(headers, metricHeader, suffix) {
  const baseHeader = metricHeader.endsWith("_value") ? metricHeader.slice(0, -6) : metricHeader;
  const candidates = [`${baseHeader}_${suffix}`, `${metricHeader}_${suffix}`];
  for (const candidate of candidates) {
    const index = headers.findIndex((header) => header === candidate);
    if (index >= 0) {
      return index;
    }
  }
  return null;
}

function metricPriority(header, valueCount, positiveCount) {
  let score = valueCount + positiveCount;

  for (const token of ["radio", "nuclear", "mercury", "co2", "co2e", "nox", "so2", "emission", "pm", "ghg"]) {
    if (header.includes(token)) {
      score += 10;
    }
  }

  if (header.endsWith("_value")) {
    score += 5;
  }

  return score;
}

function chooseRecommendedMetricKey(metricCandidates) {
  for (const preferred of PREFERRED_UPLOADED_METRICS) {
    const candidate = metricCandidates.find((item) => item.normalizedHeader === preferred);
    if (candidate) {
      return candidate.normalizedHeader;
    }
  }

  return metricCandidates[0]?.normalizedHeader ?? "";
}

function countCoordinateRows(rows, latIndex, lonIndex) {
  if (latIndex === null || lonIndex === null) {
    return 0;
  }

  let count = 0;
  for (const row of rows) {
    const latitude = parseInputNumber(row[latIndex]);
    const longitude = parseInputNumber(row[lonIndex]);
    if (isFiniteCoordinate(latitude, -90, 90) && isFiniteCoordinate(longitude, -180, 180)) {
      count += 1;
    }
  }
  return count;
}

function countMatchedBaseRows(rows, keyIndex, basePlantCodes) {
  if (keyIndex === null) {
    return 0;
  }

  let count = 0;
  for (const row of rows) {
    const plantCode = normalizePlantCode(row[keyIndex]);
    if (plantCode && basePlantCodes.has(plantCode)) {
      count += 1;
    }
  }
  return count;
}

function extractMetricMetadata(row, candidate) {
  const unit = readCell(row, candidate.unitIndex);
  const basis = readCell(row, candidate.basisIndex);
  const source = readCell(row, candidate.sourceIndex);
  const reportingYear = readCell(row, candidate.reportingYearIndex);

  if (!unit && !basis && !source && !reportingYear) {
    return null;
  }

  return {
    unit,
    basis,
    source,
    reportingYear,
  };
}

function readCell(row, index) {
  if (index === null || index === undefined || index < 0) {
    return "";
  }
  return String(row[index] ?? "").trim();
}

function selectValueToIndex(value) {
  if (value === "") {
    return null;
  }
  const index = Number(value);
  return Number.isInteger(index) ? index : null;
}

function isFiniteCoordinate(value, minimum, maximum) {
  return Number.isFinite(value) && value >= minimum && value <= maximum;
}

function normalizeHeader(value) {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

function normalizePlantCode(value) {
  if (value === null || value === undefined) {
    return "";
  }
  return String(value).trim().replace(/\.0+$/, "");
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
  if (absoluteValue > 0 && absoluteValue < 0.01) {
    return value.toExponential(2);
  }
  return numberFormatter.format(value);
}

function formatCoordinate(value) {
  return Number.isFinite(value) ? value.toFixed(4) : "No data";
}

function guessMetricLabel(rawKey) {
  const uppercaseTokens = new Map([
    ["co2", "CO2"],
    ["co2e", "CO2e"],
    ["nox", "NOx"],
    ["so2", "SO2"],
    ["n2o", "N2O"],
    ["ch4", "CH4"],
    ["pm", "PM"],
    ["pm25", "PM2.5"],
    ["pm2_5", "PM2.5"],
    ["mw", "MW"],
    ["mwh", "MWh"],
    ["lb", "lb"],
    ["lbs", "lb"],
    ["hg", "Hg"],
    ["eia", "EIA"],
    ["epa", "EPA"],
  ]);

  return rawKey
    .split("_")
    .map((token) => uppercaseTokens.get(token) ?? token.charAt(0).toUpperCase() + token.slice(1))
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
