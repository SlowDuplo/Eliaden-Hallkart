const halls = [
  { id: "all", label: "All halls" },
  { id: "A", label: "Hall A" },
  { id: "B", label: "Hall B" },
  { id: "C", label: "Hall C" },
  { id: "D", label: "Hall D" },
  { id: "U", label: "Hall U" },
];

const searchInput = document.querySelector("#search");
const filterContainer = document.querySelector("#hall-filters");
const boothList = document.querySelector("#booth-list");
const markerLayer = document.querySelector("#map-markers");
const selectedPanel = document.querySelector("#selected-booth");
const resultSummary = document.querySelector("#result-summary");
const totalCount = document.querySelector("#total-count");
const emptyState = document.querySelector("#empty-state");
const directoryFooter = document.querySelector("#directory-footer");
const mapCanvas = document.querySelector("#map-canvas");
const mapWindow = document.querySelector("#map-window");

let booths = [];
let selectedStand = null;
let activeHall = "all";
let scale = 1;

function boothName(booth) {
  return booth.exhibitors.length
    ? booth.exhibitors.join(", ")
    : "Not listed in the exhibitor directory";
}

function boothSearchText(booth) {
  return `${booth.stand} ${booth.hall} ${boothName(booth)}`.toLocaleLowerCase("nb-NO");
}

function renderFilters() {
  filterContainer.replaceChildren();

  for (const hall of halls) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "hall-filter";
    button.dataset.hall = hall.id;
    button.textContent = hall.label;
    button.setAttribute("aria-pressed", String(activeHall === hall.id));
    button.addEventListener("click", () => {
      activeHall = hall.id;
      render();
      filterContainer.querySelector(`[data-hall="${hall.id}"]`)?.focus();
    });
    filterContainer.append(button);
  }
}

function visibleBooths() {
  const query = searchInput.value.trim().toLocaleLowerCase("nb-NO");
  return booths
    .filter((booth) => activeHall === "all" || booth.hall === activeHall)
    .filter((booth) => !query || boothSearchText(booth).includes(query))
    .sort((a, b) => boothName(a).localeCompare(boothName(b), "nb"));
}

function renderList(matches) {
  boothList.replaceChildren();
  emptyState.hidden = matches.length !== 0;
  boothList.hidden = matches.length === 0;

  const groups = new Map();
  for (const booth of matches) {
    const initial = boothName(booth).charAt(0).toLocaleUpperCase("nb-NO");
    if (!groups.has(initial)) groups.set(initial, []);
    groups.get(initial).push(booth);
  }

  for (const [initial, group] of groups) {
    const section = document.createElement("section");
    section.className = "letter-group";
    const heading = document.createElement("h3");
    heading.className = "letter-heading";
    heading.textContent = initial;
    section.append(heading);

    for (const booth of group) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "booth-card";
      button.dataset.stand = booth.stand;
      button.setAttribute("aria-pressed", String(booth.stand === selectedStand));

      const name = document.createElement("span");
      name.className = "booth-name";
      name.textContent = boothName(booth);
      if (!booth.locations.length) {
        const indicator = document.createElement("span");
        indicator.className = "unmapped-indicator";
        indicator.setAttribute("aria-label", "No individual label on the floor plan");
        indicator.title = "No individual label on the floor plan";
        indicator.textContent = "○";
        name.append(indicator);
      }

      const code = document.createElement("span");
      code.className = "booth-code";
      code.textContent = booth.stand;
      button.append(name, code);
      button.addEventListener("click", () => selectBooth(booth.stand));
      section.append(button);
    }
    boothList.append(section);
  }
}

function renderMarkers(matches) {
  const matchingStands = new Set(matches.map((booth) => booth.stand));
  markerLayer.replaceChildren();

  for (const booth of booths) {
    for (const location of booth.locations) {
      const marker = document.createElement("button");
      marker.type = "button";
      marker.className = "map-pin";
      marker.style.left = `${location.x * 100}%`;
      marker.style.top = `${location.y * 100}%`;
      marker.dataset.stand = booth.stand;
      marker.setAttribute("aria-label", `${booth.stand}: ${boothName(booth)}`);
      marker.title = `${booth.stand} · ${boothName(booth)}`;
      marker.setAttribute("aria-pressed", String(booth.stand === selectedStand));
      if (!matchingStands.has(booth.stand)) marker.classList.add("is-filtered");
      if (booth.stand === selectedStand) marker.classList.add("is-selected");
      marker.addEventListener("click", () => selectBooth(booth.stand));
      markerLayer.append(marker);
    }
  }
}

function renderSelected() {
  selectedPanel.replaceChildren();
  const booth = booths.find((entry) => entry.stand === selectedStand);

  if (!booth) {
    const placeholder = document.createElement("div");
    placeholder.className = "selected-placeholder";
    placeholder.innerHTML = `
      <span class="selected-icon" aria-hidden="true">↖</span>
      <div><strong>Select a booth</strong><p>Choose a pin on the map or an exhibitor in the list.</p></div>
    `;
    selectedPanel.append(placeholder);
    return;
  }

  const content = document.createElement("div");
  content.className = "selected-content";
  const main = document.createElement("div");
  main.className = "selected-content-main";
  const icon = document.createElement("span");
  icon.className = "selected-icon";
  icon.setAttribute("aria-hidden", "true");
  icon.textContent = booth.locations.length ? "⌖" : "i";
  const text = document.createElement("div");
  text.className = "selected-title";
  const name = document.createElement("strong");
  name.textContent = boothName(booth);
  const description = document.createElement("p");
  description.textContent = booth.locations.length
    ? `Hall ${booth.hall} · Booth location highlighted on the map`
    : `Hall ${booth.hall} · No individual label for this booth on the source floor plan`;
  text.append(name, description);
  main.append(icon, text);
  const code = document.createElement("span");
  code.className = "selected-booth-code";
  code.textContent = booth.stand;
  content.append(main, code);
  selectedPanel.append(content);
}

function render() {
  const matches = visibleBooths();
  totalCount.textContent = String(booths.length);
  resultSummary.textContent = `${matches.length} ${matches.length === 1 ? "booth" : "booths"} shown`;
  directoryFooter.textContent = "Booth details and locations are based on the supplied 2026 floor plan.";
  renderFilters();
  renderList(matches);
  renderMarkers(matches);
  renderSelected();
}

function selectBooth(stand) {
  const selectedFromMap = document.activeElement.classList.contains("map-pin");
  selectedStand = stand;
  render();
  const targetSelector = selectedFromMap ? ".map-pin" : ".booth-card";
  const target = [...document.querySelectorAll(targetSelector)]
    .find((button) => button.dataset.stand === stand);
  if (selectedFromMap) {
    target?.focus({ preventScroll: true });
    return;
  }
  const listButton = target;
  listButton?.scrollIntoView({ block: "nearest" });
  listButton?.focus({ preventScroll: true });
}

function setZoom(nextScale) {
  scale = Math.max(1, Math.min(2.5, nextScale));
  mapCanvas.style.width = `${scale * 100}%`;
  if (scale === 1) {
    mapWindow.scrollTo({ top: 0, left: 0, behavior: "smooth" });
  }
}

function setInitialSelectionFromHash() {
  const stand = decodeURIComponent(window.location.hash.slice(1)).toUpperCase();
  if (booths.some((booth) => booth.stand === stand)) {
    selectedStand = stand;
    activeHall = booths.find((booth) => booth.stand === stand).hall;
  }
}

async function start() {
  try {
    const response = await fetch("./data/exhibitors.json");
    if (!response.ok) throw new Error(`Could not load booth data (${response.status}).`);
    const data = await response.json();
    if (!Array.isArray(data.booths) || data.booths.length === 0) {
      throw new Error("The booth data file is empty or invalid.");
    }
    booths = data.booths;
    setInitialSelectionFromHash();
    render();
  } catch (error) {
    console.error(error);
    resultSummary.textContent = "The booth directory could not be loaded. Reload the page to try again.";
    boothList.hidden = true;
    emptyState.hidden = true;
    selectedPanel.textContent = error.message;
  }
}

searchInput.addEventListener("input", render);
searchInput.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    searchInput.value = "";
    render();
  }
});
document.querySelector("#zoom-in").addEventListener("click", () => setZoom(scale + 0.25));
document.querySelector("#zoom-out").addEventListener("click", () => setZoom(scale - 0.25));
document.querySelector("#zoom-fit").addEventListener("click", () => setZoom(1));
document.addEventListener("keydown", (event) => {
  if (event.key === "/" && document.activeElement !== searchInput) {
    event.preventDefault();
    searchInput.focus();
  }
});

start();
