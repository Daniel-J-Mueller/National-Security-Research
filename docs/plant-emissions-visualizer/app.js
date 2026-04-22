const DATA_URL = "../../data/private/visualizer/plants_reference.json";
const PROFILE_SOURCE_PATH = "data/private/eia860_2024/plant_profiles_private.csv";
const HEAT_PANE = "heatPane";
const POINT_PANE = "pointPane";

const EMISSION_DEFINITIONS = [
  { key: "co2_emissions_value", label: "CO2 Emissions (tons)" },
  { key: "co2e_emissions_value", label: "CO2e Emissions (tons)" },
  { key: "ch4_emissions_value", label: "CH4 Emissions (lb)" },
  { key: "n2o_emissions_value", label: "N2O Emissions (lb)" },
  { key: "so2_emissions_value", label: "SO2 Emissions" },
  { key: "nox_emissions_value", label: "NOx Emissions (tons)" },
  { key: "particulate_matter_emissions_value", label: "Particulate Matter Emissions" },
  { key: "mercury_emissions_value", label: "Mercury Emissions (lb)" },
  { key: "radioisotopic_emissions_value", label: "Radioisotopic Emissions" },
];

const PREFERRED_EMISSIONS = EMISSION_DEFINITIONS.map((definition) => definition.key);

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

const HEADER_LABEL_OVERRIDES = {
  plant_code: "Plant Code",
  utility_id: "Utility ID",
  zip_code: "ZIP Code",
  nerc_region: "NERC Region",
  co2e_emissions_value: "CO2e Emissions Value",
  co2e_emissions_unit: "CO2e Emissions Unit",
  co2e_emissions_basis: "CO2e Emissions Basis",
  co2e_emissions_source: "CO2e Emissions Source",
  co2e_emissions_reporting_year: "CO2e Emissions Reporting Year",
  ch4_emissions_value: "CH4 Emissions Value",
  ch4_emissions_unit: "CH4 Emissions Unit",
  ch4_emissions_basis: "CH4 Emissions Basis",
  ch4_emissions_source: "CH4 Emissions Source",
  ch4_emissions_reporting_year: "CH4 Emissions Reporting Year",
  n2o_emissions_value: "N2O Emissions Value",
  n2o_emissions_unit: "N2O Emissions Unit",
  n2o_emissions_basis: "N2O Emissions Basis",
  n2o_emissions_source: "N2O Emissions Source",
  n2o_emissions_reporting_year: "N2O Emissions Reporting Year",
  nox_emissions_value: "NOx Emissions Value",
  nox_emissions_unit: "NOx Emissions Unit",
  nox_emissions_basis: "NOx Emissions Basis",
  nox_emissions_source: "NOx Emissions Source",
  nox_emissions_reporting_year: "NOx Emissions Reporting Year",
  so2_emissions_value: "SO2 Emissions Value",
  so2_emissions_unit: "SO2 Emissions Unit",
  so2_emissions_basis: "SO2 Emissions Basis",
  so2_emissions_source: "SO2 Emissions Source",
  so2_emissions_reporting_year: "SO2 Emissions Reporting Year",
  particulate_matter_emissions_value: "Particulate Matter Emissions Value",
  particulate_matter_emissions_unit: "Particulate Matter Emissions Unit",
  particulate_matter_emissions_basis: "Particulate Matter Emissions Basis",
  particulate_matter_emissions_source: "Particulate Matter Emissions Source",
  particulate_matter_emissions_reporting_year: "Particulate Matter Emissions Reporting Year",
};

const state = {
  headers: [],
  plants: [],
  filteredPlants: [],
  availableEmissionDefinitions: [],
  activeEmissionKey: "",
  activePlantCode: "",
  hoverPlantCode: "",
  map: null,
  pointLayer: null,
  heatLayer: null,
  canvasRenderer: null,
};

const numberFormatter = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });
const integerFormatter = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

const elements = {
  sourceSummary: document.getElementById("source-summary"),
  emissionSelect: document.getElementById("emission-select"),
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
  setStatus("Loading private visualizer asset...");

  try {
    const response = await fetch(DATA_URL, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const payload = await response.json();
    if (!payload || !Array.isArray(payload.plants) || !payload.plants.length) {
      throw new Error("plants_reference.json does not contain any mapped plant rows.");
    }

    state.headers = Array.isArray(payload.headers) && payload.headers.length
      ? payload.headers.map((value) => String(value ?? "").trim())
      : inferHeadersFromPlants(payload.plants);
    state.availableEmissionDefinitions = EMISSION_DEFINITIONS.filter((definition) =>
      payload.plants.some((plant) => Object.prototype.hasOwnProperty.call(plant, definition.key)),
    );

    if (!state.availableEmissionDefinitions.length) {
      throw new Error("No supported emission columns were found in plants_reference.json.");
    }

    state.plants = payload.plants
      .map((plant, index) => hydratePlant(plant, index))
      .filter((plant) => Number.isFinite(plant.latitude) && Number.isFinite(plant.longitude));

    if (!state.plants.length) {
      throw new Error("No plant rows with valid coordinates were found in plants_reference.json.");
    }

    state.activeEmissionKey = preferredEmissionKey(state.availableEmissionDefinitions, state.plants);
    updateSourceSummary(payload.metadata, payload.plants.length, state.plants.length);
    populateEmissionOptions();
    populateFilters();
    refreshView({ fitBounds: true });
  } catch (error) {
    console.error(error);
    setStatus(
      "Could not load the private visualizer asset. Serve the repo root with a local HTTP server before opening this page.",
      "error",
    );
    elements.sourceSummary.innerHTML =
      "Could not read <code>data/private/visualizer/plants_reference.json</code> from the browser.";
  }
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

function bindEvents() {
  elements.emissionSelect.addEventListener("change", () => {
    state.activeEmissionKey = elements.emissionSelect.value;
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
}

function hydratePlant(sourcePlant, rowIndex) {
  const plantCode = normalizePlantCode(sourcePlant.plant_code) || `row-${rowIndex + 1}`;
  const emissions = {};
  for (const definition of state.availableEmissionDefinitions) {
    emissions[definition.key] = toNumber(sourcePlant[definition.key]);
  }

  const plant = {
    plant_code: plantCode,
    plant_name: stringValue(sourcePlant.plant_name) || `Plant ${plantCode}`,
    utility_id: stringValue(sourcePlant.utility_id),
    utility_name: stringValue(sourcePlant.utility_name),
    street_address: stringValue(sourcePlant.street_address),
    city: stringValue(sourcePlant.city),
    county: stringValue(sourcePlant.county),
    state: stringValue(sourcePlant.state),
    zip_code: stringValue(sourcePlant.zip_code),
    latitude: toNumber(sourcePlant.latitude),
    longitude: toNumber(sourcePlant.longitude),
    balancing_authority_name: stringValue(sourcePlant.balancing_authority_name),
    primary_fuel_code: stringValue(sourcePlant.primary_fuel_code),
    primary_technology: stringValue(sourcePlant.primary_technology),
    source_dataset: stringValue(sourcePlant.source_dataset),
    rawRow: Array.isArray(sourcePlant.raw_row)
      ? sourcePlant.raw_row.map((value) => stringValue(value))
      : state.headers.map((header) => stringValue(sourcePlant[header])),
    emissions,
  };

  plant.searchText = buildSearchText(plant);
  return plant;
}

function buildSearchText(plant) {
  return [
    plant.plant_code,
    plant.plant_name,
    plant.utility_name,
    plant.street_address,
    plant.county,
    plant.city,
    plant.state,
    plant.primary_fuel_code,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function updateSourceSummary(metadata, totalRows, mappedRows) {
  const sourceFiles = Array.isArray(metadata?.source_files) ? metadata.source_files : [];
  const sourceSuffix = sourceFiles.length
    ? ` Built from <code>${escapeHtml(sourceFiles[0].replaceAll("\\", "/"))}</code>.`
    : ` Built from <code>${escapeHtml(PROFILE_SOURCE_PATH)}</code>.`;
  elements.sourceSummary.innerHTML =
    `Auto-loaded <code>data/private/visualizer/plants_reference.json</code> with ` +
    `${integerFormatter.format(totalRows)} plant rows. ${integerFormatter.format(mappedRows)} rows include ` +
    `coordinates and are ready to map.${sourceSuffix}`;
}

function populateEmissionOptions() {
  elements.emissionSelect.replaceChildren();
  for (const definition of state.availableEmissionDefinitions) {
    const option = document.createElement("option");
    option.value = definition.key;
    option.textContent = definition.label;
    elements.emissionSelect.append(option);
  }
  elements.emissionSelect.value = state.activeEmissionKey;
}

function preferredEmissionKey(definitions, plants) {
  for (const preferred of PREFERRED_EMISSIONS) {
    if (!definitions.some((definition) => definition.key === preferred)) {
      continue;
    }
    if (plants.some((plant) => Number.isFinite(getEmissionValue(plant, preferred)))) {
      return preferred;
    }
  }
  return definitions[0]?.key ?? EMISSION_DEFINITIONS[0].key;
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

function refreshView(options = {}) {
  state.filteredPlants = applyFilters();

  if (!state.filteredPlants.some((plant) => plant.plant_code === state.activePlantCode)) {
    state.activePlantCode = "";
  }
  if (!state.filteredPlants.some((plant) => plant.plant_code === state.hoverPlantCode)) {
    state.hoverPlantCode = "";
  }

  const emissionStats = buildEmissionStats(state.filteredPlants);
  renderSummary(emissionStats);
  renderHeatLayer(emissionStats);
  renderPointLayer(emissionStats);
  renderResults(emissionStats);
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
      const emissionValue = getEmissionValue(plant, state.activeEmissionKey);
      if (!Number.isFinite(emissionValue) || emissionValue < minimumValue) {
        return false;
      }
    }
    return true;
  });
}

function buildEmissionStats(plants) {
  const values = [];
  let total = 0;
  let maxPlant = null;
  let maxValue = Number.NEGATIVE_INFINITY;
  let positiveCount = 0;

  for (const plant of plants) {
    const value = getEmissionValue(plant, state.activeEmissionKey);
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
      maxPlant = plant;
    }
  }

  return {
    values,
    countWithEmission: values.length,
    positiveCount,
    total,
    maxValue: Number.isFinite(maxValue) ? maxValue : null,
    maxPlant,
  };
}

function renderSummary(emissionStats) {
  elements.visibleCount.textContent = integerFormatter.format(state.filteredPlants.length);
  elements.metricTotal.textContent = emissionStats.countWithEmission ? formatMetric(emissionStats.total) : "No data";
  elements.metricMax.textContent = emissionStats.maxPlant
    ? `${emissionStats.maxPlant.plant_name} (${formatMetric(emissionStats.maxValue)})`
    : "No data";
  elements.metricName.textContent = emissionLabel(state.activeEmissionKey);
}

function renderHeatLayer(emissionStats) {
  if (state.heatLayer) {
    state.map.removeLayer(state.heatLayer);
    state.heatLayer = null;
  }

  if (elements.viewSelect.value === "points" || typeof L.heatLayer !== "function") {
    return;
  }

  const maxValue = emissionStats.maxValue ?? 0;
  if (maxValue <= 0) {
    return;
  }

  const heatPoints = state.filteredPlants
    .map((plant) => {
      const value = getEmissionValue(plant, state.activeEmissionKey);
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

function renderPointLayer(emissionStats) {
  state.pointLayer.clearLayers();

  if (elements.viewSelect.value === "heat") {
    return;
  }

  const maxValue = emissionStats.maxValue ?? 0;
  for (const plant of state.filteredPlants) {
    const value = getEmissionValue(plant, state.activeEmissionKey);
    const isActive = plant.plant_code === state.activePlantCode;
    const defaultStyle = {
      pane: POINT_PANE,
      renderer: state.canvasRenderer,
      radius: markerRadius(value, maxValue, isActive),
      weight: isActive ? 1.8 : 0.8,
      color: isActive ? "rgba(31, 26, 22, 0.75)" : "rgba(31, 26, 22, 0.38)",
      fillColor: markerColor(plant, value, maxValue),
      fillOpacity: Number.isFinite(value) ? (isActive ? 0.92 : 0.82) : 0.46,
    };

    const marker = L.circleMarker([plant.latitude, plant.longitude], defaultStyle);
    const hoverStyle = {
      weight: Math.max(defaultStyle.weight, 1.5),
      color: "rgba(31, 26, 22, 0.8)",
      radius: defaultStyle.radius + 1.2,
    };

    marker.on("mouseover", () => {
      state.hoverPlantCode = plant.plant_code;
      marker.setStyle(hoverStyle);
      marker.unbindTooltip();
      marker
        .bindTooltip(buildHoverSummaryHtml(plant), {
          direction: "top",
          offset: [0, -10],
          opacity: 1,
          className: "plant-hover-tooltip",
        })
        .openTooltip();
      renderDetail();
    });

    marker.on("mouseout", () => {
      if (state.hoverPlantCode === plant.plant_code) {
        state.hoverPlantCode = "";
      }
      marker.setStyle(defaultStyle);
      marker.closeTooltip();
      marker.unbindTooltip();
      renderDetail();
    });

    marker.on("click", () => {
      focusPlant(plant, { flyTo: false });
    });

    state.pointLayer.addLayer(marker);
  }
}

function renderResults(emissionStats) {
  const orderedPlants = [...state.filteredPlants].sort((left, right) => {
    const leftValue = getEmissionValue(left, state.activeEmissionKey) ?? Number.NEGATIVE_INFINITY;
    const rightValue = getEmissionValue(right, state.activeEmissionKey) ?? Number.NEGATIVE_INFINITY;
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
      valueLine.textContent = `${emissionLabel(state.activeEmissionKey)}: ${displayEmissionValue(plant, state.activeEmissionKey)}`;

      button.append(title, location, valueLine);
      button.addEventListener("mouseenter", () => {
        state.hoverPlantCode = plant.plant_code;
        renderDetail();
      });
      button.addEventListener("mouseleave", () => {
        if (state.hoverPlantCode === plant.plant_code) {
          state.hoverPlantCode = "";
          renderDetail();
        }
      });
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

  if (!emissionStats.countWithEmission) {
    setStatus(`${emissionLabel(state.activeEmissionKey)} has no numeric values in the current view.`);
    return;
  }

  if (elements.viewSelect.value !== "points" && emissionStats.positiveCount === 0) {
    setStatus(`${emissionLabel(state.activeEmissionKey)} has numeric values, but none are above zero, so the heatmap is empty.`);
    return;
  }

  setStatus(
    `Viewing ${integerFormatter.format(state.filteredPlants.length)} plants using ${emissionLabel(state.activeEmissionKey)}.`,
  );
}

function renderDetail() {
  const plant = detailPlant();
  if (!plant) {
    elements.detailPanel.textContent =
      "Hover or click a plant point or a result row to inspect the full source row.";
    return;
  }

  const previewLabel =
    state.hoverPlantCode === plant.plant_code ? "Hover preview from plant_profiles_private.csv" : "Selected plant";

  const summaryRows = [
    ["Active emission", emissionLabel(state.activeEmissionKey)],
    ["Emission value", displayEmissionValue(plant, state.activeEmissionKey)],
    ["Plant code", plant.plant_code],
    ["Utility", plant.utility_name || "No data"],
    ["Address", formatAddress(plant)],
    ["County", plant.county || "No data"],
    ["Primary fuel", plant.primary_fuel_code || "No data"],
    ["Technology", plant.primary_technology || "No data"],
    ["Balancing authority", plant.balancing_authority_name || "No data"],
    ["Latitude", formatCoordinate(plant.latitude)],
    ["Longitude", formatCoordinate(plant.longitude)],
  ]
    .map(([label, value]) => buildDetailRowHtml(label, value))
    .join("");

  const fullRow = state.headers
    .map((header, index) =>
      buildDetailRowHtml(humanizeHeader(header), readRawValue(plant.rawRow, index), normalizeHeader(header) === state.activeEmissionKey),
    )
    .join("");

  elements.detailPanel.innerHTML = [
    `<div class="detail-head">`,
    `<strong>${escapeHtml(plant.plant_name || `Plant ${plant.plant_code}`)}</strong>`,
    `<div class="microcopy">${escapeHtml(previewLabel)}</div>`,
    `</div>`,
    `<div class="detail-section-label">Active view</div>`,
    `<div class="detail-grid">${summaryRows}</div>`,
    `<div class="detail-section-label">Full source row</div>`,
    `<div class="detail-grid detail-grid--dense">${fullRow}</div>`,
  ].join("");
}

function detailPlant() {
  if (state.hoverPlantCode) {
    return state.filteredPlants.find((plant) => plant.plant_code === state.hoverPlantCode) ?? null;
  }
  if (state.activePlantCode) {
    return state.filteredPlants.find((plant) => plant.plant_code === state.activePlantCode) ?? null;
  }
  return null;
}

function focusPlant(plant, options = {}) {
  state.activePlantCode = plant.plant_code;
  state.hoverPlantCode = "";
  const emissionStats = buildEmissionStats(state.filteredPlants);
  renderPointLayer(emissionStats);
  renderResults(emissionStats);
  renderDetail();

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

function getEmissionValue(plant, emissionKey) {
  return toNumber(plant.emissions?.[emissionKey]);
}

function displayEmissionValue(plant, emissionKey) {
  const value = getEmissionValue(plant, emissionKey);
  return Number.isFinite(value) ? formatMetric(value) : "No data";
}

function emissionLabel(emissionKey) {
  return state.availableEmissionDefinitions.find((definition) => definition.key === emissionKey)?.label ?? emissionKey;
}

function markerRadius(value, maxValue, isActive = false) {
  const baseRadius = !Number.isFinite(value) || maxValue <= 0 ? 4.2 : 4 + Math.sqrt(value / maxValue) * 10;
  return isActive ? baseRadius + 1.2 : baseRadius;
}

function markerColor(plant, value, maxValue) {
  if (!Number.isFinite(value) || maxValue <= 0) {
    return FUEL_COLORS[plant.primary_fuel_code] ?? "#8d7b68";
  }
  const ratio = Math.max(0, Math.min(1, Math.sqrt(value / maxValue)));
  return interpolateColor("#fee08b", "#9e0142", ratio);
}

function buildHoverSummaryHtml(plant) {
  return [
    `<div class="popup-title">${escapeHtml(plant.plant_name || `Plant ${plant.plant_code}`)}</div>`,
    `<div class="popup-line">${escapeHtml(plant.utility_name || "Unknown utility")}</div>`,
    `<div class="popup-line">${escapeHtml(formatAddress(plant))}</div>`,
    `<div class="popup-line">${escapeHtml(emissionLabel(state.activeEmissionKey))}: ${escapeHtml(
      displayEmissionValue(plant, state.activeEmissionKey),
    )}</div>`,
    `<div class="popup-line">Plant code: ${escapeHtml(plant.plant_code)}</div>`,
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

function readRawValue(row, index) {
  if (!Number.isInteger(index) || index < 0) {
    return "No data";
  }
  return String(row[index] ?? "").trim() || "No data";
}

function inferHeadersFromPlants(plants) {
  const orderedHeaders = [];
  const seen = new Set();

  for (const preferred of [
    "plant_code",
    "plant_name",
    "utility_id",
    "utility_name",
    "street_address",
    "city",
    "county",
    "state",
    "zip_code",
    "latitude",
    "longitude",
  ]) {
    if (plants.some((plant) => Object.prototype.hasOwnProperty.call(plant, preferred))) {
      orderedHeaders.push(preferred);
      seen.add(preferred);
    }
  }

  for (const plant of plants) {
    for (const key of Object.keys(plant)) {
      if (key === "raw_row" || seen.has(key)) {
        continue;
      }
      seen.add(key);
      orderedHeaders.push(key);
    }
  }

  return orderedHeaders;
}

function stringValue(value) {
  if (value === null || value === undefined) {
    return "";
  }
  return String(value).trim();
}

function formatAddress(plant) {
  const parts = [plant.street_address, plant.city, plant.state, plant.zip_code].filter(Boolean);
  return parts.length ? parts.join(", ") : "No data";
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
    rows: rows.filter((currentRow) => currentRow.some((value) => String(value ?? "").trim().length)),
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

function normalizeHeader(value) {
  return String(value ?? "")
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
    ["pm", "PM"],
    ["pm25", "PM2.5"],
    ["pm2_5", "PM2.5"],
    ["mw", "MW"],
    ["mwh", "MWh"],
    ["kv", "kV"],
    ["kv_total", "kV Total"],
    ["lb", "lb"],
    ["lbs", "lb"],
    ["gpm", "gpm"],
    ["cfm", "cfm"],
    ["fgd", "FGD"],
    ["fgp", "FGP"],
    ["eia", "EIA"],
    ["epa", "EPA"],
    ["zip", "ZIP"],
    ["id", "ID"],
    ["ids", "IDs"],
    ["nerc", "NERC"],
  ]);

  return value
    .split("_")
    .filter(Boolean)
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
