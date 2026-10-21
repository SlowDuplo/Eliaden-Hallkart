const searchInput = document.querySelector("#search");
const filterContainer = document.querySelector("#hall-filters");
const boothList = document.querySelector("#booth-list");
const markerLayer = document.querySelector("#map-markers");
const selectedPanel = document.querySelector("#selected-booth");
const resultSummary = document.querySelector("#result-summary");
const totalCount = document.querySelector("#total-count");
const emptyState = document.querySelector("#empty-state");
const mapCanvas = document.querySelector("#map-canvas");
const mapWindow = document.querySelector("#map-window");
const mapArtwork = document.querySelector("#map-artwork");

let booths = [];
let exhibitors = [];
let hiddenStands = new Set();
let halls = [];
let selectedStand = null;
let selectedExhibitorId = null;
let selectedPanelDismissed = false;
let activeHall = "all";
let scale = 1;
let mapDrag = null;

function boothName(booth) {
  return booth.exhibitors.length
    ? booth.exhibitors.join(", ")
    : "Not listed in the exhibitor directory";
}

function standHall(stand) {
  return stand.startsWith("UR-") ? "U" : stand.charAt(0);
}

function profileStandNumbers(exhibitor) {
  return exhibitor.stands.map((stand) => stand.number).filter(Boolean);
}

function visibleProfileStandNumbers(exhibitor) {
  return profileStandNumbers(exhibitor).filter((stand) =>
    activeHall === "all" || standHall(stand) === activeHall,
  );
}

function boothDisplayName(booth) {
  const names = exhibitors
    .filter((exhibitor) => profileStandNumbers(exhibitor).includes(booth.stand))
    .map((exhibitor) => exhibitor.name);
  if (names.length) return names.join(", ");
  return hiddenStands.has(booth.stand) ? "Exhibitor details unavailable" : boothName(booth);
}

function exhibitorSearchText(exhibitor) {
  const details = exhibitor.stands.flatMap((stand) => [
    stand.number,
    stand.description,
    ...stand.categories,
  ]);
  return [
    exhibitor.name,
    exhibitor.country_code,
    exhibitor.website,
    ...details,
  ].join(" ").toLocaleLowerCase("nb-NO");
}

function makeExhibitors(profileData) {
  const profiles = profileData.exhibitors.map((exhibitor) => ({
    ...exhibitor,
    id: String(exhibitor.id),
    stands: Array.isArray(exhibitor.stands) ? exhibitor.stands : [],
  }));
  const apiStands = new Set(profiles.flatMap(profileStandNumbers));

  for (const booth of booths) {
    if (apiStands.has(booth.stand) || hiddenStands.has(booth.stand)) continue;
    for (const name of booth.exhibitors) {
      profiles.push({
        id: `pdf-${booth.stand}-${profiles.length}`,
        name,
        website: "",
        logo: "",
        country_code: "",
        social_links: [],
        stands: [{
          name,
          number: booth.stand,
          description: "",
          categories: [],
          logo: "",
        }],
      });
    }
  }

  return profiles;
}

function updateEventDetails(data) {
  const eventInfo = data.event ?? {};
  const name = eventInfo.name || "Event";
  const year = eventInfo.year ? String(eventInfo.year) : "";
  const title = [name, year].filter(Boolean).join(" ");
  const hallNames = halls.map((hall) => hall.label);
  const eventDetails = [eventInfo.dates, eventInfo.venue].filter(Boolean).join(" · ");

  document.title = `${title} — Hall map`;
  document.querySelector('meta[name="description"]').content =
    `Search exhibitors and booth locations for ${title}.`;
  document.querySelector("#event-name").textContent = name;
  document.querySelector("#event-year").textContent = year;
  document.querySelector("#event-year").hidden = !year;
  document.querySelector("#event-details").textContent = eventDetails;
  document.querySelector("#event-details").hidden = !eventDetails;
  document.querySelector(".map-app").setAttribute("aria-label", `Interactive ${title} hall map`);
  mapArtwork.alt = `${title} floor plan showing ${hallNames.join(", ") || "the exhibition halls"}`;
}

function renderFilters() {
  filterContainer.replaceChildren();

  const options = [{ id: "all", label: "All halls" }, ...halls];
  for (const hall of options) {
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

function visibleExhibitors() {
  const query = searchInput.value.trim().toLocaleLowerCase("nb-NO");
  return exhibitors
    .filter((exhibitor) =>
      activeHall === "all" ||
      exhibitor.stands.some((stand) => standHall(stand.number) === activeHall),
    )
    .filter((exhibitor) => !query || exhibitorSearchText(exhibitor).includes(query))
    .sort((a, b) => a.name.localeCompare(b.name, "nb"));
}

function renderList(matches) {
  boothList.replaceChildren();
  emptyState.hidden = matches.length !== 0;
  boothList.hidden = matches.length === 0;

  const groups = new Map();
  for (const exhibitor of matches) {
    const initial = exhibitor.name.charAt(0).toLocaleUpperCase("nb-NO");
    if (!groups.has(initial)) groups.set(initial, []);
    groups.get(initial).push(exhibitor);
  }

  for (const [initial, group] of groups) {
    const section = document.createElement("section");
    section.className = "letter-group";
    const heading = document.createElement("h3");
    heading.className = "letter-heading";
    heading.textContent = initial;
    section.append(heading);

    for (const exhibitor of group) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "booth-card exhibitor-card";
      button.dataset.exhibitorId = exhibitor.id;
      button.setAttribute("aria-pressed", String(exhibitor.id === selectedExhibitorId));
      if (exhibitor.id === selectedExhibitorId) button.classList.add("is-selected");

      const name = document.createElement("span");
      name.className = "booth-name";
      name.textContent = exhibitor.name;

      const code = document.createElement("span");
      code.className = "booth-code";
      code.textContent = profileStandNumbers(exhibitor).join(", ") || "Details";
      button.append(name, code);
      button.addEventListener("click", () => selectExhibitor(exhibitor.id));
      section.append(button);
    }
    boothList.append(section);
  }
}

function renderMarkers(matches) {
  const matchingStands = new Set(matches.flatMap(visibleProfileStandNumbers));
  if (!searchInput.value.trim()) {
    for (const booth of booths) {
      if (activeHall === "all" || booth.hall === activeHall) {
        matchingStands.add(booth.stand);
      }
    }
  }
  markerLayer.replaceChildren();

  for (const booth of booths) {
    for (const location of booth.locations) {
      const geometry = location.geometry;
      if (!geometry) throw new Error(`Missing map geometry for booth ${booth.stand}.`);

      const boothButton = document.createElement("button");
      boothButton.type = "button";
      boothButton.className = "booth-region";
      boothButton.style.left = `${geometry.x * 100}%`;
      boothButton.style.top = `${geometry.y * 100}%`;
      boothButton.style.width = `${geometry.width * 100}%`;
      boothButton.style.height = `${geometry.height * 100}%`;
      boothButton.style.clipPath = `polygon(${geometry.points
        .map(([x, y]) => `${x * 100}% ${y * 100}%`)
        .join(", ")})`;
      boothButton.dataset.stand = booth.stand;
      boothButton.setAttribute("aria-label", `${booth.stand}: ${boothDisplayName(booth)}`);
      boothButton.title = `${booth.stand} · ${boothDisplayName(booth)}`;
      const isSelected = booth.stand === selectedStand;
      boothButton.setAttribute("aria-pressed", String(isSelected));
      if (!matchingStands.has(booth.stand)) boothButton.classList.add("is-filtered");
      if (isSelected) boothButton.classList.add("is-selected");
      boothButton.addEventListener("click", () => selectBooth(booth.stand));
      markerLayer.append(boothButton);
    }
  }
}

function createExternalLink(label, href) {
  if (!href) return null;
  let url;
  try {
    url = new URL(href);
  } catch {
    return null;
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") return null;

  const link = document.createElement("a");
  link.href = url.href;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.textContent = label;
  return link;
}

function renderExhibitorDetails(exhibitor) {
  const details = document.createElement("article");
  details.className = "exhibitor-details";

  const heading = document.createElement("div");
  heading.className = "exhibitor-details-heading";
  const logo = document.createElement("img");
  logo.className = "exhibitor-logo";
  logo.alt = `${exhibitor.name} logo`;
  logo.loading = "lazy";
  const fallback = document.createElement("span");
  fallback.className = "exhibitor-logo-fallback";
  fallback.textContent = exhibitor.name.charAt(0).toLocaleUpperCase("nb-NO");
  const logoUrl = exhibitor.logo || "";
  logo.hidden = !logoUrl;
  fallback.hidden = Boolean(logoUrl);
  if (logoUrl) {
    logo.src = logoUrl;
    logo.addEventListener("error", () => {
      logo.hidden = true;
      fallback.hidden = false;
    }, { once: true });
  }

  const titleBlock = document.createElement("div");
  titleBlock.className = "exhibitor-details-title";
  const title = document.createElement("h3");
  title.textContent = exhibitor.name;
  titleBlock.append(title);
  if (exhibitor.country_code) {
    const country = document.createElement("span");
    country.className = "exhibitor-country";
    country.textContent = exhibitor.country_code;
    titleBlock.append(country);
  }
  heading.append(logo, fallback, titleBlock);
  details.append(heading);

  const standNumbers = profileStandNumbers(exhibitor);
  if (standNumbers.length) {
    const stands = document.createElement("div");
    stands.className = "exhibitor-stands";
    for (const stand of standNumbers) {
      const badge = document.createElement("span");
      badge.className = "selected-booth-code";
      badge.textContent = stand;
      stands.append(badge);
    }
    details.append(stands);
  }

  const selectedStandInfo = exhibitor.stands.find((stand) => stand.number === selectedStand);
  const descriptionText = selectedStandInfo?.description ||
    exhibitor.stands.find((stand) => stand.description)?.description;
  const description = document.createElement("p");
  description.className = "exhibitor-description";
  description.textContent = descriptionText || "Company information from the exhibitor directory.";
  details.append(description);

  const categoryNames = [...new Set(exhibitor.stands.flatMap((stand) => stand.categories || []))];
  if (categoryNames.length) {
    const categories = document.createElement("div");
    categories.className = "exhibitor-categories";
    for (const category of categoryNames) {
      const tag = document.createElement("span");
      tag.className = "exhibitor-category";
      tag.textContent = category;
      categories.append(tag);
    }
    details.append(categories);
  }

  const links = document.createElement("div");
  links.className = "exhibitor-links";
  const website = createExternalLink("Visit website", exhibitor.website);
  if (website) links.append(website);
  for (const social of exhibitor.social_links || []) {
    const link = createExternalLink(social.platform, social.url);
    if (link) links.append(link);
  }
  if (links.childElementCount) details.append(links);

  return details;
}

function renderSelected() {
  selectedPanel.replaceChildren();
  selectedPanel.hidden = selectedPanelDismissed;
  if (selectedPanelDismissed) return;

  const exhibitor = exhibitors.find((entry) => entry.id === selectedExhibitorId);
  if (exhibitor) {
    selectedPanel.append(createSelectedCloseButton(), renderExhibitorDetails(exhibitor));
    return;
  }

  const booth = booths.find((entry) => entry.stand === selectedStand);
  if (!booth) {
    const placeholder = document.createElement("div");
    placeholder.className = "selected-placeholder";
    placeholder.innerHTML = `
      <span class="selected-icon" aria-hidden="true">↖</span>
      <div><strong>Select an exhibitor</strong><p>Choose a pin on the map or an exhibitor in the list.</p></div>
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
  const isHidden = hiddenStands.has(booth.stand);
  name.textContent = isHidden ? "Exhibitor details unavailable" : boothName(booth);
  const description = document.createElement("p");
  description.textContent = isHidden
    ? "This exhibitor has not made its profile details public."
    : booth.locations.length
    ? `Hall ${booth.hall} · Booth location highlighted on the map`
    : `Hall ${booth.hall} · No individual label for this booth on the source floor plan`;
  text.append(name, description);
  main.append(icon, text);
  const code = document.createElement("span");
  code.className = "selected-booth-code";
  code.textContent = booth.stand;
  content.append(main, code);
  selectedPanel.append(createSelectedCloseButton(), content);
}

function createSelectedCloseButton() {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "selected-close";
  button.setAttribute("aria-label", "Close selected exhibitor details");
  button.title = "Close";
  button.textContent = "×";
  button.addEventListener("click", () => {
    selectedStand = null;
    selectedExhibitorId = null;
    selectedPanelDismissed = true;
    updateBoothUrl(null);
    render();
  });
  return button;
}

function render() {
  const matches = visibleExhibitors();
  totalCount.textContent = String(exhibitors.length);
  resultSummary.textContent = `${matches.length} ${matches.length === 1 ? "exhibitor" : "exhibitors"} shown`;
  renderFilters();
  renderList(matches);
  renderMarkers(matches);
  renderSelected();
}

function selectBooth(stand) {
  const selectedFromMap = markerLayer.contains(document.activeElement);
  selectedPanelDismissed = false;
  selectedStand = stand;
  updateBoothUrl(stand);
  selectedExhibitorId = exhibitors.find((exhibitor) =>
    exhibitor.stands.some((entry) => entry.number === stand),
  )?.id ?? null;
  render();
  const target = [...markerLayer.querySelectorAll(".booth-region")]
    .find((button) => button.dataset.stand === stand);
  if (selectedFromMap) {
    target?.focus({ preventScroll: true });
    return;
  }
  const exhibitorCard = [...boothList.querySelectorAll(".exhibitor-card")]
    .find((button) => button.dataset.exhibitorId === selectedExhibitorId);
  exhibitorCard?.scrollIntoView({ block: "nearest" });
  exhibitorCard?.focus({ preventScroll: true });
}

function selectExhibitor(id) {
  const exhibitor = exhibitors.find((entry) => entry.id === id);
  if (!exhibitor) return;
  selectedPanelDismissed = false;
  selectedExhibitorId = id;
  const hallStands = exhibitor.stands.filter((entry) =>
    activeHall === "all" || standHall(entry.number) === activeHall,
  );
  const stand = hallStands.find((entry) =>
    booths.some((booth) => booth.stand === entry.number && booth.locations.length),
  ) ?? hallStands[0] ?? exhibitor.stands[0];
  selectedStand = stand?.number ?? null;
  updateBoothUrl(selectedStand);
  render();
  const target = [...boothList.querySelectorAll(".exhibitor-card")]
    .find((button) => button.dataset.exhibitorId === id);
  target?.scrollIntoView({ block: "nearest" });
  target?.focus({ preventScroll: true });
}

function setZoom(nextScale) {
  scale = Math.max(1, Math.min(5, nextScale));
  mapCanvas.style.width = `${scale * 100}%`;
  if (scale === 1) {
    mapWindow.scrollTo({ top: 0, left: 0, behavior: "smooth" });
  }
}

mapWindow.addEventListener("pointerdown", (event) => {
  if (!event.isPrimary || event.button !== 0 || event.target.closest("button, a, input")) return;
  mapDrag = {
    pointerId: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    scrollLeft: mapWindow.scrollLeft,
    scrollTop: mapWindow.scrollTop,
  };
  mapWindow.setPointerCapture(event.pointerId);
  mapWindow.classList.add("is-dragging");
});

mapWindow.addEventListener("pointermove", (event) => {
  if (!mapDrag || event.pointerId !== mapDrag.pointerId) return;
  mapWindow.scrollLeft = mapDrag.scrollLeft - (event.clientX - mapDrag.startX);
  mapWindow.scrollTop = mapDrag.scrollTop - (event.clientY - mapDrag.startY);
  event.preventDefault();
});

function finishMapDrag(event) {
  if (!mapDrag || event.pointerId !== mapDrag.pointerId) return;
  mapDrag = null;
  mapWindow.classList.remove("is-dragging");
}

mapWindow.addEventListener("pointerup", finishMapDrag);
mapWindow.addEventListener("pointercancel", finishMapDrag);
mapWindow.addEventListener("lostpointercapture", finishMapDrag);

function updateBoothUrl(stand) {
  const url = new URL(window.location.href);
  const queryBooth = url.searchParams.has("booth") || url.searchParams.has("boothId");
  if (queryBooth) {
    url.searchParams.delete("booth");
    url.searchParams.delete("boothId");
    if (stand) url.searchParams.set("booth", stand);
    url.hash = "";
  } else {
    url.hash = stand ? encodeURIComponent(stand) : "";
  }
  window.history.replaceState(null, "", url);
}

function setInitialSelectionFromUrl() {
  const url = new URL(window.location.href);
  const queryStand = url.searchParams.get("booth") || url.searchParams.get("boothId");
  const stand = (queryStand || decodeURIComponent(url.hash.slice(1))).toUpperCase();
  const booth = booths.find((entry) => entry.stand === stand);
  if (booth) {
    selectedStand = stand;
    activeHall = booth.hall;
    selectedExhibitorId = exhibitors.find((exhibitor) =>
      exhibitor.stands.some((entry) => entry.number === stand),
    )?.id ?? null;
  }
}

function loadMap(data) {
  const source = data.map?.image || "./assets/hall-map.png";
  return new Promise((resolve, reject) => {
    const finish = () => {
      mapArtwork.removeEventListener("load", handleLoad);
      mapArtwork.removeEventListener("error", handleError);
    };
    const handleLoad = () => {
      finish();
      if (mapArtwork.naturalWidth && mapArtwork.naturalHeight) {
        resolve();
      } else {
        reject(new Error("The map artwork has no readable image dimensions."));
      }
    };
    const handleError = () => {
      finish();
      reject(new Error(`Could not load map artwork from "${source}".`));
    };

    if (mapArtwork.getAttribute("src") === source && mapArtwork.complete) {
      handleLoad();
      return;
    }

    mapArtwork.addEventListener("load", handleLoad);
    mapArtwork.addEventListener("error", handleError);
    if (mapArtwork.getAttribute("src") !== source) mapArtwork.src = source;
    if (mapArtwork.complete) handleLoad();
  });
}

async function start() {
  try {
    const [boothResponse, profileResponse] = await Promise.all([
      fetch("./data/exhibitors.json"),
      fetch("./data/exhibitor-profiles.json"),
    ]);
    if (!boothResponse.ok) throw new Error(`Could not load booth data (${boothResponse.status}).`);
    if (!profileResponse.ok) {
      throw new Error(`Could not load exhibitor profiles (${profileResponse.status}).`);
    }
    const [data, profileData] = await Promise.all([
      boothResponse.json(),
      profileResponse.json(),
    ]);
    if (!Array.isArray(data.booths) || data.booths.length === 0) {
      throw new Error("The booth data file is empty or invalid.");
    }
    if (!Array.isArray(profileData.exhibitors) || profileData.exhibitors.length === 0) {
      throw new Error("The exhibitor profile data file is empty or invalid.");
    }

    booths = data.booths;
    hiddenStands = new Set(Array.isArray(profileData.hidden_stands) ? profileData.hidden_stands : []);
    exhibitors = makeExhibitors(profileData);
    halls = Array.isArray(data.halls) && data.halls.length
      ? data.halls
      : [...new Set(booths.map((booth) => booth.hall))].sort().map((id) => ({ id, label: `Hall ${id}` }));
    updateEventDetails(data);
    await loadMap(data);
    setInitialSelectionFromUrl();
    render();
  } catch (error) {
    console.error(error);
    resultSummary.textContent = "The hall map could not be loaded. Check its data and artwork files, then reload.";
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
