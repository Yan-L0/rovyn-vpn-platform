export interface User {
  id: string
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
