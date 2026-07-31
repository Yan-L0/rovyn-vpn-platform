const navigation = [...document.querySelectorAll("[data-view]")];
const screens = [...document.querySelectorAll("[data-screen]")];

function openView(name) {
  screens.forEach((screen) => screen.classList.toggle("is-visible", screen.dataset.screen === name));
  navigation.forEach((button) => button.classList.toggle("is-active", button.dataset.view === name));
  window.scrollTo({ top: 0, behavior: "smooth" });
}

navigation.forEach((button) => button.addEventListener("click", () => openView(button.dataset.view)));
document.querySelectorAll("[data-open]").forEach((button) => {
  button.addEventListener("click", () => openView(button.dataset.open));
});

const trafficYear = [
  { name: "январь", value: 21.4 },
  { name: "февраль", value: 28.8 },
  { name: "март", value: 25.1 },
  { name: "апрель", value: 27.4 },
  { name: "май", value: 35.9 },
  { name: "июнь", value: 42.3 },
  { name: "июль", value: 18.7 },
  { name: "август", value: null },
  { name: "сентябрь", value: null },
  { name: "октябрь", value: null },
  { name: "ноябрь", value: null },
  { name: "декабрь", value: null },
];

const currentTrafficMonth = 6;
const trafficValue = document.querySelector("#traffic-value");
const trafficCaption = document.querySelector("#traffic-caption");
const trafficYearLabel = document.querySelector("#traffic-year");
const trafficBars = [...document.querySelectorAll("#traffic-bars button")];

function formatTraffic(value) {
  return `${value.toFixed(1).replace(".", ",")} ГБ`;
}

function selectTrafficMonth(index) {
  const selected = trafficYear[index];
  if (!selected || selected.value === null) return;

  trafficValue.textContent = formatTraffic(selected.value);
  trafficCaption.textContent = index === currentTrafficMonth
    ? `за ${selected.name} · текущий месяц`
    : `за ${selected.name} 2026`;
  trafficBars.forEach((bar, barIndex) => {
    bar.classList.toggle("is-selected", barIndex === index);
    bar.setAttribute("aria-pressed", String(barIndex === index));
  });
}

function renderTrafficYear() {
  const maxTraffic = Math.max(...trafficYear.map((month) => month.value ?? 0));
  trafficYearLabel.textContent = "2026 год";

  trafficBars.forEach((bar, index) => {
    const month = trafficYear[index];
    const barFill = bar.querySelector("i");
    const hasData = month.value !== null;
    const height = hasData ? Math.max(18, (month.value / maxTraffic) * 100) : 8;

    barFill.style.setProperty("--bar-height", `${height}%`);
    bar.classList.toggle("is-current", index === currentTrafficMonth);
    bar.classList.toggle("is-future", !hasData);
    bar.disabled = !hasData;
    bar.dataset.tip = hasData ? `${month.name} · ${formatTraffic(month.value)}` : month.name;
    bar.setAttribute(
      "aria-label",
      hasData ? `${month.name}: ${formatTraffic(month.value)}` : `${month.name}: данных пока нет`,
    );
    bar.addEventListener("click", () => selectTrafficMonth(index));
  });

  selectTrafficMonth(currentTrafficMonth);
}

renderTrafficYear();
