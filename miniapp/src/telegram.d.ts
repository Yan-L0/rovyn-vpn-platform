interface TelegramWebApp {
  initData: string
  initDataUnsafe?: {
    user?: {
      id: number
      first_name?: string
      last_name?: string
      photo_url?: string
    }
  }
  colorScheme: 'light' | 'dark'
  ready(): void
  expand(): void
  close(): void
  enableClosingConfirmation(): void
  disableVerticalSwipes?(): void
  enableVerticalSwipes?(): void
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
