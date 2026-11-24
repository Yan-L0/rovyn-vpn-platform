// Called only after identifying a personal device. Its upstream quota is per-device.
module.exports = function sharedTrafficHeader(previous, usage) {
  const expire = String(previous || '').match(/(?:^|;)\s*expire=(\d+)\s*(?:;|$)/i)
  const fields = []
  const used = usage?.used_bytes
  const total = usage?.traffic_limit_bytes
  if ([used, total].every(n => Number.isSafeInteger(n) && n >= 0)) {
    fields.push('upload=0', `download=${used}`, `total=${total}`)
  }
  if (expire) fields.push(`expire=${expire[1]}`)
  return fields.length ? fields.join('; ') : undefined
}
