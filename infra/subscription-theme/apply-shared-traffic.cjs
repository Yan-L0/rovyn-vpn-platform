const meter = require('./shared-traffic.cjs')

module.exports = async function applySharedTraffic(service, clientIp, key, res) {
  // Both lookups share a deadline so a working profile can still be delivered.
  const controller = new AbortController()
  let timer
  const deadline = new Promise(resolve => {
    timer = setTimeout(() => {
      controller.abort()
      resolve(null)
    }, 5000)
  })
  let device
  let usage
  try {
    const info = await Promise.race([service.getSubscriptionInfo(clientIp, key), deadline])
    device = /^dev_([a-f0-9]{32})$/i.exec(info?.response?.response?.user?.username || '')
    if (!device) return
    const response = await fetch('https://bot.yanlo.biz/api/v2/subscription/device-usage', {
      method: 'POST',
      redirect: 'error',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ device_id: device[1], link_key: key }),
      signal: controller.signal,
    })
    if (response.ok) usage = await response.json()
  } catch {
    // A failed lookup must not prevent delivery of the subscription body.
  } finally {
    clearTimeout(timer)
    if (device) {
      const header = 'subscription-userinfo'
      const value = meter(res.getHeader(header), usage)
      if (value === undefined) res.removeHeader(header)
      else res.setHeader(header, value)
    }
  }
}
