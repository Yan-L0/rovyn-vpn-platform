const navButtons = [...document.querySelectorAll("[data-view]")];
const screens = [...document.querySelectorAll("[data-screen]")];

function openView(viewName) {
  screens.forEach((screen) => {
    screen.classList.toggle("is-visible", screen.dataset.screen === viewName);
  });

  navButtons.forEach((button) => {
    button.classList.toggle("is-active", button.dataset.view === viewName);
  });

  document.querySelector(`[data-screen="${viewName}"]`)?.scrollTo({ top: 0, behavior: "instant" });
}

navButtons.forEach((button) => {
  button.addEventListener("click", () => openView(button.dataset.view));
});

document.querySelector(".device-shortcut")?.addEventListener("click", () => openView("devices"));
document.querySelector(".round-arrow")?.addEventListener("click", () => openView("plans"));

const powerButton = document.querySelector(".power-control");
powerButton?.addEventListener("click", () => {
  const enabled = powerButton.classList.toggle("is-on");
  powerButton.setAttribute("aria-label", enabled ? "Отключить VPN" : "Подключить VPN");
  document.querySelector(".connection-copy h1").innerHTML = enabled
    ? "Ваш интернет<br />защищён"
    : "VPN временно<br />отключён";
  document.querySelector(".connection-copy p").textContent = enabled
    ? "Амстердам · 24 мс"
    : "Нажмите, чтобы подключиться";
});
