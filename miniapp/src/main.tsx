import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './styles.css'

const telegram = window.Telegram?.WebApp
const cabinetBootColor = window.location.pathname.startsWith('/cabinet') ? '#0b302d' : '#050807'
telegram?.ready()
telegram?.expand()
telegram?.setHeaderColor(cabinetBootColor)
telegram?.setBackgroundColor(cabinetBootColor)
telegram?.enableClosingConfirmation()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
