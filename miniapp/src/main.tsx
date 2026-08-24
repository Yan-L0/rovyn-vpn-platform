import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './styles.css'

const telegram = window.Telegram?.WebApp
const cabinetBootColor = window.location.pathname.startsWith('/cabinet') ? '#0b302d' : '#050807'
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
