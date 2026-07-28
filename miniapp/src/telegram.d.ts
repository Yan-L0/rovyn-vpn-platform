interface TelegramWebApp {
  initData: string
  colorScheme: 'light' | 'dark'
  ready(): void
  expand(): void
  close(): void
  enableClosingConfirmation(): void
  setHeaderColor(color: string): void
  setBackgroundColor(color: string): void
  openLink(url: string): void
  HapticFeedback?: {
    impactOccurred(style: 'light' | 'medium' | 'heavy'): void
  }
}

interface Window {
  Telegram?: {
    WebApp: TelegramWebApp
  }
}
