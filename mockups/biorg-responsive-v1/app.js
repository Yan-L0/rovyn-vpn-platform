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

const power = document.querySelector(".power-control");
power?.addEventListener("click", () => {
  const connected = power.classList.toggle("is-on");
  power.setAttribute("aria-label", connected ? "Отключить VPN" : "Подключить VPN");
  document.querySelector(".hero-status strong").textContent = connected ? "VPN подключён" : "VPN отключён";
  document.querySelector(".status-dot").style.background = connected ? "var(--moss)" : "#ad705e";
});
