import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './styles.css'

const telegram = window.Telegram?.WebApp
telegram?.ready()
telegram?.expand()
telegram?.setHeaderColor('#050807')
telegram?.setBackgroundColor('#050807')
telegram?.enableClosingConfirmation()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
