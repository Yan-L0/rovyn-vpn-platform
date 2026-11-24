// Loaded synchronously immediately after #sbpg, before the upstream app consumes it.
(() => {
  const source = document.getElementById('sbpg')?.dataset.panel
  if (!source) return
  const data = JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(source), c => c.charCodeAt(0)))).response
  const user = data?.user
  if (!user?.username || !user.userStatus) return
  const device = /^dev_([a-f0-9]{32})$/i.exec(user.username)
  const renewal = 'https://t.me/rovynBot?startapp=cabinet&mode=fullscreen'
  const host = document.createElement('rovyn-subscription')
  const root = host.attachShadow({mode:'open'})
  root.innerHTML = `
    <link rel="stylesheet" href="/assets/rovyn-summary.css?v=1">
    <section class="card" aria-labelledby="device-title">
      <div class="hero"><div class="identity"><div class="status"><b aria-hidden="true"></b><span></span></div>
        <h1 id="device-title"></h1><p class="term"></p></div>
        <div class="orbit" aria-hidden="true"><div class="track"></div><div class="planet"><svg viewBox="0 0 24 24"><rect x="6" y="2" width="12" height="20" rx="3"/><path d="M11 18h2"/></svg></div></div>
      </div>
      <div class="balance"><div class="caption"></div><div class="amount"><strong></strong> <span class="unit"></span></div>
        <div class="meter" aria-hidden="true"><i></i></div><div class="scale"><span></span><span></span></div></div>
      <button class="open"><span></span><svg aria-hidden="true" viewBox="0 0 24 24"><path d="M5 12h14m-6-6 6 6-6 6"/></svg></button>
    </section>
    <button type="button" class="guide" aria-expanded="false"><span class="guide-icon"><svg aria-hidden="true" viewBox="0 0 24 24"><path d="M12 3v12m-5-5 5 5 5-5M4 16v4h16v-4"/></svg></span><strong>Как установить Happ</strong><span class="toggle"></span></button>`
  const get = selector => root.querySelector(selector)
  const guide = get('.guide')
  let installation
  let action
  let inactive
  guide.onclick = () => {
    const open = guide.getAttribute('aria-expanded') !== 'true'
    guide.setAttribute('aria-expanded', String(open))
    installation.classList.toggle('rovyn-folded', !open)
  }
  get('.open').onclick = () => {
    if (inactive) location.assign(renewal)
    else if (action) action.click()
    else if (guide.getAttribute('aria-expanded') !== 'true') guide.click()
  }
  const number = new Intl.NumberFormat('ru-RU', {maximumFractionDigits:2})
  const gib = bytes => number.format(bytes / 2 ** 30) + ' ГБ'
  function legacyBytes(text) {
    const match = /^([\d.,]+)\s*(B|[KMGT]i?B)?$/i.exec(String(text ?? ''))
    if (!match) return null
    const power = 'BKMGT'.indexOf((match[2] || 'B')[0].toUpperCase())
    return Number(match[1].replace(',', '.')) * 1024 ** power
  }
  window.renderRovynSummary = (usage, name) => {
    const original = document.querySelector('.mantine-Card-root:has([class*="_infoBlock_"])')
    const grid = document.querySelector('[class*="_appsGrid_"]')
    installation = grid?.closest('.mantine-Card-root')
    if (!original || !installation || installation === original) return
    if (host.previousElementSibling !== original) original.after(host)
    original.classList.add('rovyn-folded')
    installation.classList.toggle('rovyn-folded', guide.getAttribute('aria-expanded') !== 'true')
    const selected = grid.querySelector('[class*="_appButtonActive_"]')
    action = selected?.textContent.trim().toLowerCase().includes('happ') ?
      [...installation.querySelectorAll('button,a')].find(el => /^(добавить подписку|add subscription)$/i.test(el.textContent.trim())) : null
    const limit = device ? usage?.traffic_limit_bytes : legacyBytes(user.trafficLimit)
    const used = device ? usage?.used_bytes : legacyBytes(user.trafficUsed)
    const expiredAt = new Date(user.expiresAt)
    const validDate = Boolean(user.expiresAt) && Number.isFinite(expiredAt.getTime())
    const expired = user.userStatus === 'EXPIRED' || (validDate && expiredAt <= new Date())
    const exhausted = user.userStatus === 'LIMITED' || (limit > 0 && used != null && used >= limit)
    inactive = expired || exhausted || user.userStatus !== 'ACTIVE'
    get('.card').dataset.state = inactive ? 'expired' : 'active'
    get('.status span').textContent = inactive ? 'Подписка неактивна' : 'Подписка активна'
    get('h1').textContent = name || (device ? 'Устройство · ' + device[1].slice(0,8) : user.username)
    const date = validDate ? expiredAt.toLocaleDateString('ru-RU',{day:'numeric',month:'long',year:'numeric'}) : ''
    get('.term').textContent = expired ? ('Срок закончился ' + date).trim() : exhausted ? 'Лимит трафика исчерпан' : inactive ? 'Доступ отключён' : date ? 'Действует до ' + date : ''
    get('.caption').textContent = expired ? 'Остаток на конец периода' : 'Остаток общего трафика'
    const measured = Number.isFinite(limit) && Number.isFinite(used) && limit > 0
    const remaining = measured ? Math.max(0, limit-used) : null
    get('.amount strong').textContent = limit === 0 ? '∞' : measured ? number.format(remaining / 2 ** 30) : '—'
    get('.unit').textContent = measured ? 'ГБ' : ''
    get('.meter').hidden = !measured
    if (measured) get('.meter i').style.width = Math.min(100, 100*remaining/limit) + '%'
    get('.scale span').textContent = Number.isFinite(used) ? 'Потрачено ' + gib(used) : 'Расход уточняется'
    get('.scale span:last-child').textContent = limit === 0 ? 'Безлимит' : limit > 0 ? 'Всего ' + gib(limit) : ''
    get('.open span').textContent = inactive ? 'Продлить подписку' : action ? 'Открыть в Happ' : 'Настроить подключение'
  }
})()
