const words={Subscription:'Rovyn',Username:'Имя пользователя',Status:'Статус',Active:'Активна',Expires:'Действует до',Bandwidth:'Трафик',Installation:'Установка','App Installation':'Установка приложения','Add Subscription':'Добавить подписку'};
Object.assign(words, {
  Inactive: 'Неактивна',
  Disabled: 'Доступ отключён',
  Expired: 'Срок подписки истёк',
  Limited: 'Лимит трафика исчерпан',
  "In the main section, click the large power button in the center to connect to VPN. Don't forget to select a server from the server list. If needed, choose another server from the server list.":
    'В главном разделе нажмите большую кнопку включения в центре для подключения. Не забудьте выбрать сервер в списке серверов. При необходимости выберите другой сервер из списка серверов.',
  'Connect and use': 'Подключение и использование',
  'Choose the version for your device, click the button below and install the app.':
    'Выберите подходящую версию для вашего устройства, нажмите на кнопку ниже и установите приложение.',
  'Click the button below — the app will open and the subscription will be added automatically.':
    'Нажмите кнопку ниже — приложение откроется, и подписка добавится автоматически.',
  'Click the button below — the app will open and the subscription will be added automatically':
    'Нажмите кнопку ниже — приложение откроется, и подписка добавится автоматически.',
  'Open the page in App Store and install the app. Launch it, in the VPN configuration permission window click Allow and enter your passcode.':
    'Откройте страницу в App Store и установите приложение. Запустите его, в окне разрешения конфигурации нажмите Allow и введите свой пароль.',
});
function keepHappOnly() {
  document.querySelectorAll('[class*="_appsGrid_"]').forEach(grid => {
    const buttons = [...grid.querySelectorAll('button')];
    const happ = buttons.find(button =>
      button.querySelector('[class*="_appName_"]')?.textContent.trim() === 'Happ');
    let notice = grid.parentElement.querySelector('.rovyn-client-unavailable');
    if (!happ && !notice) {
      notice = document.createElement('p');
      notice.className = 'rovyn-client-unavailable';
      notice.textContent = 'Для этой платформы Happ пока не доступен на странице подключения.';
      grid.after(notice);
    }
    if (notice) notice.hidden = !!happ;
    buttons.forEach(button => {
      button.classList.toggle('rovyn-other-client', button !== happ);
    });
    if (happ && buttons.some(button => button !== happ && /_appButtonActive_/.test(button.className))) {
      happ.click();
    }
  });
}
const deviceLabel = new URLSearchParams(window.location.hash.slice(1))
  .get('rovynDevice')?.trim().slice(0, 128);

let deviceId;
let sharedUsage;
let usageRequest;

function refreshSharedUsage() {
  if (!deviceId || usageRequest) return;
  const linkKey = location.pathname.replace(/\/$/, '').split('/').pop();
  usageRequest = fetch('https://bot.yanlo.biz/api/v2/subscription/device-usage', {
    method: 'POST',
    body: JSON.stringify({ device_id: deviceId, link_key: linkKey }),
    cache: 'no-store',
    credentials: 'omit',
    redirect: 'error',
    signal: AbortSignal.timeout(5000),
  }).then(response => response.ok ? response.json() : null)
    .then(usage => {
      sharedUsage = Number.isSafeInteger(usage?.traffic_limit_bytes) && usage.traffic_limit_bytes >= 0
        ? usage : null;
    })
    .catch(() => { sharedUsage = null; })
    .finally(() => {
      usageRequest = null;
      refreshRovyn();
    });
}

function displaySharedUsage() {
  if (!deviceId) return;
  const blocks = document.querySelectorAll('[class*="_infoBlock_"]');
  for (const block of blocks) {
    const lines = block.querySelectorAll('p');
    if (lines[0]?.textContent.trim() !== 'Трафик' && lines[0]?.textContent.trim() !== 'Общий трафик' || !lines[1]) continue;
    const format = bytes => `${new Intl.NumberFormat('ru', { maximumFractionDigits: 2 }).format(bytes / 2 ** 30)} ГБ`;
    const used = sharedUsage?.used_bytes;
    const limit = sharedUsage?.traffic_limit_bytes;
    lines[0].textContent = 'Общий трафик';
    lines[1].textContent = sharedUsage
      ? `${Number.isSafeInteger(used) && used >= 0 ? format(used) : '—'} / ${limit === 0 ? '∞' : format(limit)}`
      : '—';
  }
}

function formatDeviceNames() {
  const card = document.querySelector('.mantine-Card-root:has([class*="_infoBlock_"])');
  if (!card) return;
  const walker = document.createTreeWalker(card, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode;
    const match = node.nodeValue.trim().match(/^dev_([a-f0-9]{32})$/i);
    if (match) {
      if (!deviceId) {
        deviceId = match[1];
        refreshSharedUsage();
      }
      const shortId = match[1].slice(0, 8);
      node.nodeValue = `${deviceLabel || 'Устройство'} · ${shortId}`;
    }
  }
}

function translate(){const w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);while(w.nextNode()){const n=w.currentNode,t=n.nodeValue.trim();if(t.includes('для подключения к VPN.'))n.nodeValue=n.nodeValue.replace('для подключения к VPN.', 'для подключения.');else if(Object.hasOwn(words,t))n.nodeValue=n.nodeValue.replace(t,words[t]);else if(/^Expires in \d+ days?$/.test(t))n.nodeValue=n.nodeValue.replace(t,`Осталось дней: ${t.match(/\d+/)[0]}`)}}

// Reflect the existing countdown, without guessing if the date is unavailable.
function updateExpiryAccent() {
  document.querySelectorAll('.mantine-Card-root:has([class*="_infoBlock_"])').forEach(card => {
    const text = card.textContent;
    const match = text.match(/(?:Истекает через|Осталось дней:|Expires in)\s*(\d+)\s*(?:д(?:ень|ня|ней)|days?)?/i);
    const icon = card.querySelector('.mantine-ThemeIcon-root');
    if (!icon) return;
    const expiring = !!match && Number(match[1]) <= 3;
    icon.classList.toggle('rovyn-expiring', expiring);
    if (expiring && !icon.querySelector('.rovyn-expiry-symbol')) {
      const warning = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      warning.setAttribute('viewBox', '0 0 24 24');
      warning.setAttribute('aria-hidden', 'true');
      warning.classList.add('rovyn-expiry-symbol');
      const path = document.createElementNS(warning.namespaceURI, 'path');
      path.setAttribute('d', 'M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0z M12 8v4 M12 16h.01');
      warning.append(path);
      icon.append(warning);
    }
  });
}
// Coalesce React updates into one pass and ignore our own text mutations.
function displaySubscriptionStatus() {
  for (const block of document.querySelectorAll('[class*="_infoBlock_"]')) {
    const [label, value] = block.querySelectorAll('p');
    if (label?.textContent.trim() !== 'Статус' || !value) continue;
    const used = sharedUsage?.used_bytes;
    const limit = sharedUsage?.traffic_limit_bytes;
    const exhausted = limit > 0 && Number.isSafeInteger(used) && used >= limit;
    if (exhausted && value.textContent.trim() === 'Активна') {
      value.textContent = 'Лимит трафика исчерпан';
      value.dataset.rovynQuota = '1';
    } else if (!exhausted && value.dataset.rovynQuota) {
      if (value.textContent === 'Лимит трафика исчерпан') value.textContent = 'Активна';
      delete value.dataset.rovynQuota;
    }
    value.classList.toggle('rovyn-status-inactive', value.textContent.trim() !== 'Активна');
  }
}

function refreshRovyn() {
  observer.disconnect();
  translate();
  formatDeviceNames();
  displaySharedUsage();
  displaySubscriptionStatus();
  keepHappOnly();
  updateExpiryAccent();
  setupPlatformPicker();
  const support = document.querySelector('.header-wrapper a.mantine-ActionIcon-root');
  if (support) {
    support.href = 'https://t.me/product_vpn';
    support.setAttribute('aria-label', 'Поддержка в Telegram');
  }
  const qr = document.querySelector('._modalContent_1qevm_1 img[src^="data:image/svg+xml"]');
  if (qr) {
    const source = qr.getAttribute('src');
    const recolored = source.replace(/%23161B22/gi, '%23ffffff').replace(/%2322d3ee/gi, '%230c2724');
    if (recolored !== source) qr.setAttribute('src', recolored);
  }
  observer.observe(document.body, {childList:true, subtree:true, characterData:true});
}
const platformIcons = {
  ios:'M8 2h8v20H8z M11 19h2',
  android:'M6 8h12v10H6z M8 8 6 4 M16 8l2-4 M9 12h.01 M15 12h.01',
  macos:'M5 3h14v18H5z M8 8v2 M16 8v2 M12 4l-2 9h3v7 M8 16q4 3 8-1',
  windows:'M3 5l18-2v18L3 19z M11 4v16 M3 12h18',
  androidtv:'M3 5h18v12H3z M8 21h8 M12 17v4',
  appletv:'M3 5h18v12H3z M10 8l5 3-5 3z M8 21h8'
};

function platformIcon(value) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('aria-hidden', 'true');
  const path = document.createElementNS(svg.namespaceURI, 'path');
  path.setAttribute('d', platformIcons[value.toLowerCase()] || platformIcons.macos);
  svg.append(path);
  return svg;
}

function setupPlatformPicker() {
  const select = document.querySelector('select.mantine-NativeSelect-input');
  if (!select) return;
  const wrapper = select.closest('.mantine-NativeSelect-root');
  let picker = wrapper.querySelector('.rovyn-platform');
  if (!picker) {
    picker = document.createElement('details');
    picker.className = 'rovyn-platform';
    const trigger = document.createElement('summary');
    const list = document.createElement('div');
    list.className = 'rovyn-platform-list';
    picker.append(trigger, list);
    wrapper.append(picker);
    select.closest('.mantine-NativeSelect-wrapper').hidden = true;
    for (const option of select.options) {
      const button = document.createElement('button');
      button.type = 'button';
      button.value = option.value;
      button.append(platformIcon(option.value), option.textContent);
      button.addEventListener('click', () => {
        select.value = button.value;
        select.dispatchEvent(new Event('change', {bubbles:true}));
        picker.open = false;
        trigger.focus();
      });
      list.append(button);
    }
    picker.addEventListener('keydown', event => {
      if (event.key === 'Escape' && picker.open) {
        event.preventDefault();
        picker.open = false;
        trigger.focus();
      }
    });
    picker.addEventListener('focusout', event => {
      if (!picker.contains(event.relatedTarget)) picker.open = false;
    });
  }
  const trigger = picker.querySelector('summary');
  const label = select.selectedOptions[0]?.textContent || 'Платформа';
  if (trigger.textContent !== label) {
    trigger.replaceChildren(platformIcon(select.value), label);
    trigger.setAttribute('aria-label', 'Платформа: ' + label);
  }
  for (const button of picker.querySelectorAll('button')) {
    button.setAttribute('aria-pressed', String(button.value === select.value));
  }
}
document.addEventListener('pointerdown', event => {
  const picker = document.querySelector('.rovyn-platform[open]');
  if (picker && !picker.contains(event.target)) picker.open = false;
});
const observer = new MutationObserver(refreshRovyn);
refreshRovyn();

window.setInterval(refreshSharedUsage, 30000);
