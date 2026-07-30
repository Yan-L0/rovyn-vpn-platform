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

const trafficHistory = {
  july: {
    value: "18,7 ГБ",
    caption: "за текущий месяц",
    bars: [24, 34, 28, 55, 42, 70, 48, 62, 78, 52, 67, 84],
  },
  june: {
    value: "42,3 ГБ",
    caption: "за июнь",
    bars: [44, 58, 47, 76, 61, 88, 53, 82, 69, 92, 64, 74],
  },
  may: {
    value: "35,9 ГБ",
    caption: "за май",
    bars: [37, 51, 68, 45, 80, 56, 71, 64, 86, 59, 73, 66],
  },
  april: {
    value: "27,4 ГБ",
    caption: "за апрель",
    bars: [29, 43, 52, 38, 66, 48, 57, 74, 49, 63, 55, 69],
  },
};

const trafficMonth = document.querySelector("#traffic-month");
const trafficValue = document.querySelector("#traffic-value");
const trafficCaption = document.querySelector("#traffic-caption");
const trafficBars = [...document.querySelectorAll("#traffic-bars i")];

function updateTraffic(month) {
  const selected = trafficHistory[month];
  if (!selected) return;

  trafficValue.textContent = selected.value;
  trafficCaption.textContent = selected.caption;
  trafficBars.forEach((bar, index) => {
    bar.style.setProperty("--bar-height", `${selected.bars[index]}%`);
  });
}

trafficMonth?.addEventListener("change", (event) => updateTraffic(event.target.value));
updateTraffic(trafficMonth?.value ?? "july");
