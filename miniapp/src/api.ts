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

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? 'http://localhost:8080'

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
  await request('/api/v1/auth/telegram', {
    method: 'POST',
    body: JSON.stringify({ init_data: initData }),
  })
}

export function loadMe(): Promise<Me> {
  return request('/api/v1/me')
}

export function loadPlans(): Promise<Plan[]> {
  return request('/api/v1/catalog/plans')
}
