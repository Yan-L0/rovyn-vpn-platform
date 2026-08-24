import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './styles.css'

const telegram = window.Telegram?.WebApp
const bootParams = new URLSearchParams(window.location.search)
const cabinetMode = window.location.pathname.startsWith('/cabinet')
  || bootParams.get('app') === '1'
  || bootParams.has('tgWebAppVersion')
  || Boolean(telegram?.initData)
const cabinetBootColor = cabinetMode ? '#0b302d' : '#050807'

if (cabinetMode) {
  document.documentElement.classList.add('cabinet-boot')
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', cabinetBootColor)

  let cabinetStyles = document.querySelector<HTMLLinkElement>('link[href^="/cabinet-v2.css"]')
  const revealCabinet = () => document.documentElement.classList.add('cabinet-styles-ready')
  if (!cabinetStyles) {
    cabinetStyles = document.createElement('link')
    cabinetStyles.rel = 'stylesheet'
    cabinetStyles.href = '/cabinet-v2.css?v=21'
    cabinetStyles.onload = revealCabinet
    cabinetStyles.onerror = revealCabinet
    document.head.append(cabinetStyles)
  } else if (cabinetStyles.sheet) {
    revealCabinet()
  } else {
    cabinetStyles.addEventListener('load', revealCabinet, { once: true })
    cabinetStyles.addEventListener('error', revealCabinet, { once: true })
  }
}

telegram?.ready()
telegram?.expand()
if (telegram?.requestFullscreen && !telegram.isFullscreen) {
  try {
    telegram.requestFullscreen()
  } catch {
    // Older Telegram clients keep the expanded full-size mode.
  }
}
telegram?.setHeaderColor(cabinetBootColor)
telegram?.setBackgroundColor(cabinetBootColor)
telegram?.enableClosingConfirmation()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
