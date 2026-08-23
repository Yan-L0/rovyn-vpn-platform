export interface User {
  id: string
  telegram_id?: number | null
  display_name: string
  locale: string | null
}

export interface Subscription {
  status: string
  plan_name: string
  expires_at: string
  traffic_limit_bytes: number
  device_limit: number
  used_bytes: number | null
}

export interface Me {
  user: User
  wallet_balance_minor: number
  wallet_currency: string
  referral_code: string
  subscription: Subscription | null
}

export interface Plan {
  id: string
  code: string
  name: string
  description: string
  duration_days: number
  traffic_limit_bytes: number
  device_limit: number
  price_minor: number
  currency: string
  server_groups: string[]
}

export interface AuthResponse {
  user: User
  csrf_token: string
  expires_at: string
}

export interface SubscriptionAccess {
  subscription_id: string
  status: string
  provider_status: string
  plan_name: string
  subscription_url: string
  starts_at: string
  expires_at: string
  device_limit: number
  usage: {
    used_bytes: number
    traffic_limit_bytes: number
    upload_bytes: number | null
    download_bytes: number | null
  }
}

export interface MonthlyUsage {
  month: number
  used_bytes: number
  has_data: boolean
}

export interface YearlyUsage {
  year: number
  current_month: number
  current_month_used_bytes: number
  updated_at: string | null
  source_status: 'fresh' | 'stale' | 'stored'
  months: MonthlyUsage[]
}

export interface Device {
  hardware_id: string
  platform: string | null
  model: string | null
  last_seen_at: string | null
}

export type OrderStatus = 'pending' | 'awaiting_payment' | 'paid' | 'cancelled' | 'expired' | 'failed' | string
export type PaymentStatus = 'pending' | 'waiting_for_capture' | 'succeeded' | 'cancelled' | 'failed' | string

export interface CheckoutOrder {
  order_id: string
  status: OrderStatus
  amount_minor: number
  currency: string
  payment_id: string
  payment_status: PaymentStatus
  confirmation_url: string | null
}

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? 'http://localhost:8080'
const CSRF_STORAGE_KEY = 'nova.csrf-token'

function saveCsrfToken(token: string): void {
  try {
    window.sessionStorage.setItem(CSRF_STORAGE_KEY, token)
  } catch {
    // sessionStorage may be unavailable in hardened embedded browsers.
  }
}

function csrfToken(): string {
  try {
    return window.sessionStorage.getItem(CSRF_STORAGE_KEY) ?? ''
  } catch {
    return ''
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...init,
      credentials: 'include',
      cache: 'no-store',
      headers: {
        'Content-Type': 'application/json',
        ...(init?.headers ?? {}),
      },
    })
  } catch {
    throw new Error('Сервис временно недоступен')
  }
  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: 'Сервис временно недоступен' }))
    throw new Error(typeof detail.detail === 'string' ? detail.detail : 'Сервис временно недоступен')
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export async function authenticate(initData: string): Promise<void> {
  const response = await request<AuthResponse>('/api/v1/auth/telegram', {
    method: 'POST',
    body: JSON.stringify({ init_data: initData }),
  })
  saveCsrfToken(response.csrf_token)
}

export function loadMe(): Promise<Me> {
  return request('/api/v1/me')
}

export function loadPlans(): Promise<Plan[]> {
  return request('/api/v1/catalog/plans')
}

export function loadSubscriptionAccess(): Promise<SubscriptionAccess> {
  return request('/api/v2/subscription/access')
}

export function loadYearlyTraffic(year?: number): Promise<YearlyUsage> {
  const query = year ? `?year=${year}` : ''
  return request(`/api/v2/traffic/year${query}`)
}

export function loadDevices(): Promise<Device[]> {
  return request('/api/v2/devices')
}

export function revokeDevice(hardwareId: string): Promise<void> {
  const token = csrfToken()
  if (!token) return Promise.reject(new Error('Сессия устарела. Войдите в кабинет ещё раз.'))
  return request(`/api/v2/devices/${encodeURIComponent(hardwareId)}`, {
    method: 'DELETE',
    headers: { 'X-CSRF-Token': token },
  })
}

export function createSbpOrder(planId: string, idempotencyKey: string): Promise<CheckoutOrder> {
  const token = csrfToken()
  if (!token) {
    return Promise.reject(new Error('Сессия оплаты устарела. Войдите в кабинет ещё раз.'))
  }
  return request('/api/v1/orders', {
    method: 'POST',
    headers: {
      'X-CSRF-Token': token,
      'Idempotency-Key': idempotencyKey,
    },
    body: JSON.stringify({ plan_id: planId }),
  })
}

export function loadOrder(orderId: string): Promise<CheckoutOrder> {
  return request(`/api/v1/orders/${encodeURIComponent(orderId)}`)
}
