import { useCallback, useEffect, useRef, useState } from 'react'
import {
  authenticate,
  createSbpOrder,
  findAdminUser,
  grantAdminAccess,
  loadAdminAccess,
  loadDevices,
  loadMe,
  loadOrder,
  loadPlans,
  loadSubscriptionAccess,
  loadYearlyTraffic,
  revokeDevice,
  type CheckoutOrder,
  type AdminGrantResult,
  type AdminUserLookup,
  type Device,
  type Me,
  type Plan,
  type SubscriptionAccess,
  type YearlyUsage,
} from './api'

type CabinetView = 'home' | 'plans' | 'devices' | 'support' | 'profile' | 'admin'
type ModalState = null | {
  kicker: string
  title: string
  copy: string
  action?: string
  onAction?: () => void | Promise<void>
}

const views = new Set<CabinetView>(['home', 'plans', 'devices', 'support', 'profile', 'admin'])
const monthNames = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь']
const monthLetters = ['Я', 'Ф', 'М', 'А', 'М', 'И', 'И', 'А', 'С', 'О', 'Н', 'Д']
const visualPreview = import.meta.env.VITE_CABINET_PREVIEW === 'true'

const previewMe: Me = {
  user: { id: 'preview-user', telegram_id: 100000001, display_name: 'Пользователь', locale: 'ru' },
  wallet_balance_minor: 0,
  wallet_currency: 'RUB',
  referral_code: 'ROVYN-PREVIEW',
  subscription: { status: 'active', plan_name: 'NOVA Год', expires_at: '2027-07-21T12:00:00Z', traffic_limit_bytes: 0, device_limit: 5, used_bytes: 20_079_054_848 },
}
const previewPlans: Plan[] = [
  { id: 'preview-month', code: 'MONTH', name: 'NOVA Месяц', description: 'Чтобы познакомиться', duration_days: 30, traffic_limit_bytes: 0, device_limit: 5, price_minor: 10_500, currency: 'RUB', server_groups: [] },
  { id: 'preview-year', code: 'YEAR', name: 'NOVA Год', description: 'Максимальная выгода', duration_days: 365, traffic_limit_bytes: 0, device_limit: 5, price_minor: 94_500, currency: 'RUB', server_groups: [] },
  { id: 'preview-half', code: 'HALF_YEAR', name: 'NOVA Полгода', description: 'Оптимальный период', duration_days: 180, traffic_limit_bytes: 0, device_limit: 5, price_minor: 52_500, currency: 'RUB', server_groups: [] },
]
const previewAccess: SubscriptionAccess = {
  subscription_id: 'preview', status: 'active', provider_status: 'ACTIVE', plan_name: 'NOVA Год', subscription_url: 'https://example.invalid/sub/preview', starts_at: '2026-07-21T12:00:00Z', expires_at: '2027-07-21T12:00:00Z', device_limit: 5,
  usage: { used_bytes: 20_079_054_848, traffic_limit_bytes: 0, upload_bytes: 4_294_967_296, download_bytes: 15_784_087_552 },
}
const previewTraffic: YearlyUsage = {
  year: 2026, current_month: 8, current_month_used_bytes: 20_079_054_848, updated_at: new Date().toISOString(), source_status: 'fresh',
  months: [21.4, 28.8, 25.1, 27.4, 35.9, 42.3, 31.6, 18.7, 0, 0, 0, 0].map((value, index) => ({ month: index + 1, used_bytes: Math.round(value * 1024 ** 3), has_data: index < 8 })),
}
const previewDevices: Device[] = [
  { hardware_id: 'preview-mac', platform: 'macOS', model: 'MacBook Pro', last_seen_at: new Date().toISOString() },
  { hardware_id: 'preview-phone', platform: 'iOS', model: 'iPhone 17 Pro', last_seen_at: '2026-08-01T12:48:00Z' },
]

function Icon({ name }: { name: string }) {
  return <svg aria-hidden="true"><use href={`#i-${name}`} /></svg>
}

function initialView(): CabinetView {
  const hash = window.location.hash.replace('#', '') as CabinetView
  return views.has(hash) ? hash : 'home'
}

function embeddedInTelegram(): boolean {
  const params = new URLSearchParams(window.location.search)
  return params.has('tgWebAppVersion') || Boolean(window.Telegram?.WebApp.initData)
}

function formatMoney(value: number, currency = 'RUB'): string {
  return new Intl.NumberFormat('ru-RU', {
    style: 'currency', currency, maximumFractionDigits: 0,
  }).format(value / 100)
}

function formatBytes(value: number | null | undefined): string {
  if (value == null) return '—'
  const units = ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ']
  let amount = value
  let index = 0
  while (amount >= 1024 && index < units.length - 1) {
    amount /= 1024
    index += 1
  }
  return `${new Intl.NumberFormat('ru-RU', { maximumFractionDigits: index >= 3 ? 1 : 0 }).format(amount)} ${units[index]}`
}

function formatTrafficLimit(value: number | null | undefined): string {
  return value === 0 || value == null ? 'Безлимит' : formatBytes(value)
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', year: 'numeric' }).format(new Date(value))
}

function remainingDays(value: string | undefined): number {
  if (!value) return 0
  return Math.max(0, Math.ceil((new Date(value).getTime() - Date.now()) / 86_400_000))
}

function initials(name: string): string {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((word) => word[0]?.toUpperCase()).join('') || 'N'
}

function planLabel(days: number): string {
  if (days >= 360) return 'На год'
  if (days >= 170) return 'На полгода'
  if (days >= 80) return 'На 3 месяца'
  if (days >= 28) return 'На месяц'
  return `На ${days} дней`
}

function discount(days: number): string | null {
  if (days >= 360) return '−25%'
  if (days >= 170) return '−17%'
  if (days >= 80) return '−10%'
  return null
}

function planRank(plan: Plan): number {
  if (plan.duration_days >= 360) return 1
  if (plan.duration_days >= 170) return 2
  return 0
}

function planCardClass(plan: Plan): string {
  if (plan.duration_days >= 360) return 'warm'
  if (plan.duration_days >= 170) return 'dark'
  return ''
}

function planBackground(plan: Plan): string {
  return String(Math.round(plan.price_minor / 100))
}

function monthlyPriceMinor(plan: Plan): number {
  const months = Math.max(1, Math.round(plan.duration_days / 30))
  return Math.round(plan.price_minor / months / 100) * 100
}

function shortDeviceName(device: Device): string {
  return device.model || device.platform || 'Устройство'
}

function deviceIcon(device: Device): string {
  const value = `${device.platform ?? ''} ${device.model ?? ''}`.toLowerCase()
  return /iphone|android|phone|ios/.test(value) ? 'phone' : 'laptop'
}

function SvgSprite() {
  return (
    <svg className="svg-sprite" aria-hidden="true">
      <symbol id="i-home" viewBox="0 0 24 24"><path d="M3.5 10.8 12 3.7l8.5 7.1v8.1a1.6 1.6 0 0 1-1.6 1.6h-4.4v-6.2h-5v6.2H5.1a1.6 1.6 0 0 1-1.6-1.6z" /></symbol>
      <symbol id="i-plans" viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="14" rx="4" /><path d="M3 10h18M7 15h4" /></symbol>
      <symbol id="i-devices" viewBox="0 0 24 24"><rect x="2.8" y="4" width="18.4" height="12.7" rx="2.7" /><path d="M8 20h8M12 16.7V20" /></symbol>
      <symbol id="i-support" viewBox="0 0 24 24"><path d="M4.2 13.2V11a7.8 7.8 0 0 1 15.6 0v2.2" /><path d="M6.7 17.4H5.5a2.2 2.2 0 0 1-2.2-2.2v-1.4a2.2 2.2 0 0 1 2.2-2.2h1.2zm10.6 0h1.2a2.2 2.2 0 0 0 2.2-2.2v-1.4a2.2 2.2 0 0 0-2.2-2.2h-1.2z" /></symbol>
      <symbol id="i-profile" viewBox="0 0 24 24"><circle cx="12" cy="8" r="4" /><path d="M4.5 20.2c.8-4 3.3-6 7.5-6s6.7 2 7.5 6" /></symbol>
      <symbol id="i-admin" viewBox="0 0 24 24"><path d="M12 3 5 6v5c0 4.8 2.7 8.1 7 10 4.3-1.9 7-5.2 7-10V6z" /><path d="M9.5 11.5 11 13l3.5-4" /></symbol>
      <symbol id="i-arrow" viewBox="0 0 24 24"><path d="M5 12h14M14 7l5 5-5 5" /></symbol>
      <symbol id="i-plus" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14" /></symbol>
      <symbol id="i-chevron" viewBox="0 0 24 24"><path d="m9 5 7 7-7 7" /></symbol>
      <symbol id="i-laptop" viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="11.5" rx="2" /><path d="m2.5 19.5 2-4h15l2 4z" /></symbol>
      <symbol id="i-phone" viewBox="0 0 24 24"><rect x="6.5" y="2.5" width="11" height="19" rx="2.5" /><path d="M10 5h4M11 18.5h2" /></symbol>
      <symbol id="i-mail" viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="14" rx="3" /><path d="m4.5 7 7.5 6 7.5-6" /></symbol>
      <symbol id="i-telegram" viewBox="0 0 24 24"><path d="m3 11 17-7-3 16-5.3-4.2-3.1 2.8.4-5.4zM9 13.2 17.5 7" /></symbol>
      <symbol id="i-bell" viewBox="0 0 24 24"><path d="M5.5 17.5h13c-1.2-1.4-1.8-3-1.8-5V10a4.7 4.7 0 1 0-9.4 0v2.5c0 2-.6 3.6-1.8 5zM10 20h4" /></symbol>
      <symbol id="i-close" viewBox="0 0 24 24"><path d="m6 6 12 12M18 6 6 18" /></symbol>
    </svg>
  )
}

export default function CabinetV2() {
  const embedded = embeddedInTelegram()
  const browserBypass = new URLSearchParams(window.location.search).get('app') === '1'
  const [view, setView] = useState<CabinetView>(initialView)
  const [me, setMe] = useState<Me | null>(null)
  const [plans, setPlans] = useState<Plan[]>([])
  const [access, setAccess] = useState<SubscriptionAccess | null>(null)
  const [traffic, setTraffic] = useState<YearlyUsage | null>(null)
  const [devices, setDevices] = useState<Device[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [liveError, setLiveError] = useState<string | null>(null)
  const [selectedMonth, setSelectedMonth] = useState<number | null>(null)
  const [paymentPlan, setPaymentPlan] = useState<Plan | null>(null)
  const [payment, setPayment] = useState<CheckoutOrder | null>(null)
  const [paymentBusy, setPaymentBusy] = useState(false)
  const [paymentError, setPaymentError] = useState<string | null>(null)
  const [modal, setModal] = useState<ModalState>(null)
  const [modalClosing, setModalClosing] = useState(false)
  const [notifications, setNotifications] = useState(true)
  const [isOwner, setIsOwner] = useState(false)
  const [ownerChecked, setOwnerChecked] = useState(false)
  const [adminTelegramId, setAdminTelegramId] = useState('')
  const [adminUser, setAdminUser] = useState<AdminUserLookup | null>(null)
  const [adminPlanId, setAdminPlanId] = useState('')
  const [adminDeviceLimit, setAdminDeviceLimit] = useState('5')
  const [adminStartsOn, setAdminStartsOn] = useState(new Date().toISOString().slice(0, 10))
  const [adminComment, setAdminComment] = useState('Ручная выдача')
  const [adminBusy, setAdminBusy] = useState(false)
  const [adminError, setAdminError] = useState<string | null>(null)
  const [adminResult, setAdminResult] = useState<AdminGrantResult | null>(null)
  const modalRef = useRef<HTMLElement | null>(null)

  const refreshLive = useCallback(async () => {
    const results = await Promise.allSettled([loadSubscriptionAccess(), loadYearlyTraffic(), loadDevices()])
    if (results[0].status === 'fulfilled') setAccess(results[0].value)
    if (results[1].status === 'fulfilled') setTraffic(results[1].value)
    if (results[2].status === 'fulfilled') setDevices(results[2].value)
    const failed = results.find((result) => result.status === 'rejected')
    setLiveError(failed?.status === 'rejected' ? failed.reason instanceof Error ? failed.reason.message : 'Не все данные обновились' : null)
  }, [])

  useEffect(() => {
    const stylesheet = document.createElement('link')
    stylesheet.rel = 'stylesheet'
    stylesheet.href = '/cabinet-v2.css?v=15'
    stylesheet.dataset.cabinetV2 = 'true'
    document.head.append(stylesheet)
    document.body.classList.add('biorg-cabinet')
    window.Telegram?.WebApp.disableVerticalSwipes?.()
    return () => {
      stylesheet.remove()
      document.body.classList.remove('biorg-cabinet', 'modal-open')
      window.Telegram?.WebApp.enableVerticalSwipes?.()
    }
  }, [])

  useEffect(() => {
    window.Telegram?.WebApp.ready?.()
    window.Telegram?.WebApp.expand?.()
    const onHash = () => setView(initialView())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  useEffect(() => {
    async function boot() {
      try {
        if (visualPreview) {
          setMe(previewMe)
          setPlans(previewPlans)
          setAccess(previewAccess)
          setTraffic(previewTraffic)
          setDevices(previewDevices)
          setIsOwner(new URLSearchParams(window.location.search).get('admin') === '1')
          setOwnerChecked(true)
          return
        }
        if (embedded || browserBypass) await authenticate(window.Telegram?.WebApp.initData ?? '')
        const [profile, catalog, adminAccess] = await Promise.all([
          loadMe(),
          loadPlans(),
          loadAdminAccess().catch(() => ({ is_owner: false })),
        ])
        setMe(profile)
        setPlans(catalog)
        setIsOwner(adminAccess.is_owner)
        setOwnerChecked(true)
        if (profile.subscription) await refreshLive()
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : 'Не удалось открыть кабинет')
      } finally {
        setOwnerChecked(true)
        setLoading(false)
      }
    }
    void boot()
  }, [browserBypass, embedded, refreshLive])

  useEffect(() => {
    if (!adminPlanId && plans.length) setAdminPlanId(plans[0].id)
  }, [adminPlanId, plans])

  useEffect(() => {
    if (ownerChecked && !isOwner && view === 'admin') navigate('home')
  }, [isOwner, ownerChecked, view])

  useEffect(() => {
    if (!payment || ['paid', 'cancelled', 'expired', 'failed'].includes(payment.status)) return
    const timer = window.setInterval(() => void loadOrder(payment.order_id).then(setPayment).catch(() => undefined), 5000)
    return () => window.clearInterval(timer)
  }, [payment])

  useEffect(() => {
    const open = Boolean(modal || paymentPlan)
    document.body.classList.toggle('modal-open', open)
    if (open) window.setTimeout(() => modalRef.current?.focus(), 30)
  }, [modal, paymentPlan])

  useEffect(() => {
    if (!modal && !paymentPlan) return
    const grabbers = Array.from(document.querySelectorAll<HTMLElement>('.modal-grabber'))
    const starts = new WeakMap<HTMLElement, number>()
    const down = (event: PointerEvent) => {
      if (event.pointerType !== 'touch') return
      const grabber = event.currentTarget as HTMLElement
      starts.set(grabber, event.clientY)
      grabber.setPointerCapture(event.pointerId)
      grabber.parentElement?.style.setProperty('transition', 'none')
    }
    const move = (event: PointerEvent) => {
      if (event.pointerType !== 'touch') return
      const grabber = event.currentTarget as HTMLElement
      const start = starts.get(grabber)
      if (start == null) return
      const distance = Math.max(0, event.clientY - start)
      grabber.parentElement?.style.setProperty('--sheet-drag-y', `${distance}px`)
    }
    const up = (event: PointerEvent) => {
      if (event.pointerType !== 'touch') return
      const grabber = event.currentTarget as HTMLElement
      const start = starts.get(grabber)
      if (start == null) return
      const distance = event.clientY - start
      starts.delete(grabber)
      grabber.releasePointerCapture(event.pointerId)
      grabber.parentElement?.style.removeProperty('transition')
      grabber.parentElement?.style.setProperty('--sheet-drag-y', '0px')
      if (distance > 86) { if (paymentPlan) closePayment(); else closeAction() }
    }
    const cancel = (event: PointerEvent) => {
      const grabber = event.currentTarget as HTMLElement
      if (!starts.has(grabber)) return
      starts.delete(grabber)
      if (grabber.hasPointerCapture(event.pointerId)) grabber.releasePointerCapture(event.pointerId)
      grabber.parentElement?.style.removeProperty('transition')
      grabber.parentElement?.style.setProperty('--sheet-drag-y', '0px')
    }
    grabbers.forEach((grabber) => {
      grabber.addEventListener('pointerdown', down)
      grabber.addEventListener('pointermove', move)
      grabber.addEventListener('pointerup', up)
      grabber.addEventListener('pointercancel', cancel)
    })
    return () => grabbers.forEach((grabber) => {
      grabber.removeEventListener('pointerdown', down)
      grabber.removeEventListener('pointermove', move)
      grabber.removeEventListener('pointerup', up)
      grabber.removeEventListener('pointercancel', cancel)
    })
  }, [modal, paymentPlan])

  async function searchAdminUser() {
    const telegramId = Number(adminTelegramId.trim())
    if (!Number.isSafeInteger(telegramId) || telegramId <= 0) {
      setAdminError('Введите корректный Telegram ID')
      return
    }
    setAdminBusy(true)
    setAdminError(null)
    setAdminResult(null)
    try {
      setAdminUser(await findAdminUser(telegramId))
    } catch (reason) {
      setAdminError(reason instanceof Error ? reason.message : 'Не удалось найти пользователя')
    } finally {
      setAdminBusy(false)
    }
  }

  async function submitAdminGrant() {
    const telegramId = Number(adminTelegramId.trim())
    if (!Number.isSafeInteger(telegramId) || telegramId <= 0 || !adminPlanId) {
      setAdminError('Укажите Telegram ID и тариф')
      return
    }
    setAdminBusy(true)
    setAdminError(null)
    setAdminResult(null)
    try {
      const result = await grantAdminAccess({
        telegram_id: telegramId,
        plan_id: adminPlanId,
        device_limit: Number(adminDeviceLimit),
        starts_on: adminStartsOn,
        comment: adminComment,
      })
      setAdminResult(result)
      setAdminUser(await findAdminUser(telegramId))
    } catch (reason) {
      setAdminError(reason instanceof Error ? reason.message : 'Не удалось выдать доступ')
    } finally {
      setAdminBusy(false)
    }
  }

  function navigate(next: CabinetView) {
    setView(next)
    window.location.hash = next
    window.scrollTo({ top: 0, behavior: 'smooth' })
    window.Telegram?.WebApp.HapticFeedback?.impactOccurred('light')
  }

  async function startPayment() {
    if (!paymentPlan) return
    if (visualPreview) {
      setPaymentError('Визуальный режим: платёж не создаётся.')
      return
    }
    setPaymentBusy(true)
    setPaymentError(null)
    try {
      const order = await createSbpOrder(paymentPlan.id, window.crypto.randomUUID())
      setPayment(order)
      if (order.confirmation_url) {
        if (embedded && window.Telegram?.WebApp.openLink) window.Telegram.WebApp.openLink(order.confirmation_url)
        else window.open(order.confirmation_url, '_blank', 'noopener,noreferrer')
      }
    } catch (reason) {
      setPaymentError(reason instanceof Error ? reason.message : 'Не удалось создать платёж')
    } finally {
      setPaymentBusy(false)
    }
  }

  async function copyAccess() {
    if (!access?.subscription_url) return
    await navigator.clipboard.writeText(access.subscription_url)
    setModal({ kicker: 'Подключение', title: 'Ссылка скопирована.', copy: 'Откройте Happ или v2RayTun и импортируйте ссылку из буфера обмена.' })
  }

  function closePayment() {
    setModalClosing(true)
    window.setTimeout(() => { setPaymentPlan(null); setPayment(null); setModalClosing(false) }, 280)
  }

  function closeAction() {
    setModalClosing(true)
    window.setTimeout(() => { setModal(null); setModalClosing(false) }, 280)
  }

  async function removeDevice(device: Device) {
    if (visualPreview) {
      setDevices((current) => current.filter((item) => item.hardware_id !== device.hardware_id))
      setModal(null)
      return
    }
    try {
      await revokeDevice(device.hardware_id)
      await refreshLive()
      setModal(null)
    } catch (reason) {
      setModal({ kicker: 'Устройства', title: 'Не получилось удалить.', copy: reason instanceof Error ? reason.message : 'Повторите попытку позднее.' })
    }
  }

  if (loading) return <main className="cabinet-state" aria-live="polite"><div className="cabinet-loader" aria-hidden="true"><i /><i /><i /><span>R</span></div><strong>Личный кабинет</strong><p>Синхронизируем доступ…</p><small>Проверяем подписку и устройства</small></main>
  if (error || !me) return <main className="cabinet-state"><strong>Вход не выполнен</strong><p>{error || 'Откройте кабинет из официального Telegram-бота.'}</p></main>

  const active = Boolean(access && access.status !== 'expired')
  const days = remainingDays(access?.expires_at ?? me.subscription?.expires_at)
  const limit = access?.device_limit ?? me.subscription?.device_limit ?? 0
  const currentMonth = traffic?.current_month ?? new Date().getMonth() + 1
  const shownMonth = selectedMonth ?? currentMonth
  const shownUsage = traffic?.months.find((month) => month.month === shownMonth)?.used_bytes ?? 0
  const maxUsage = Math.max(1, ...(traffic?.months.map((month) => month.used_bytes) ?? [1]))
  const displayName = me.user.display_name || 'Пользователь NOVA'
  const telegramPhoto = window.Telegram?.WebApp.initDataUnsafe?.user?.photo_url
  const sortedPlans = [...plans].sort((a, b) => planRank(a) - planRank(b))
  const adminPlan = plans.find((plan) => plan.id === adminPlanId) ?? sortedPlans[0]

  return (
    <>
      <SvgSprite />
      <main className="shell">
        <header className="chrome">
          <button className="brand" onClick={() => navigate('home')} aria-label="NOVA"><i /><span>NOVA</span></button>
          <p className="section-label">Личный кабинет</p>
          <button className="avatar" onClick={() => navigate('profile')} aria-label="Открыть профиль">{telegramPhoto ? <img src={telegramPhoto} alt="" /> : initials(displayName)}</button>
        </header>

        <section className={`screen ${view === 'home' ? 'is-visible' : ''}`}>
          <div className="home-grid">
            <div className={`home-primary ${active ? 'is-active' : 'is-inactive'}`}>
              <section className="home-access-intro">
                <div className="home-access-intro__copy">
                  <p className="kicker">Ваш доступ</p>
                  <h1>Интернет<br /><span>без лишнего.</span></h1>
                  <p>{active ? 'Подписка защищает все ваши устройства. Ссылка уже готова для подключения.' : 'Выберите тариф — личная ссылка для Happ и v2RayTun появится сразу после оплаты.'}</p>
                </div>
                <div className="home-access-intro__signal" aria-hidden="true"><div className="home-access-intro__orbit"><i /><i /><i /><span>R</span></div></div>
              </section>
              <article className="home-access-plan">
                <p>{active ? 'Подписка активна' : 'Готово к подключению'}</p>
                <div><strong>{active ? access!.plan_name : 'Выберите свой ритм.'}</strong><span>{active ? days : '01'}</span></div>
                <small>{active ? `До ${formatDate(access!.expires_at)} · ${formatTrafficLimit(access!.usage.traffic_limit_bytes)}` : 'До 5 устройств · безлимитный трафик'}</small>
                <button className="home-access-plan__action" onClick={() => active ? void copyAccess() : navigate('plans')}>{active ? 'Открыть подключение' : 'Выбрать тариф'} <Icon name="arrow" /></button>
              </article>
            </div>

            <aside className="home-aside">
              <article className="subscription-panel">
                <header><p className="kicker">Срок подписки</p><small>{active ? `до ${formatDate(access!.expires_at)}` : 'период не начат'}</small></header>
                <div className="subscription-date"><strong>{days}</strong><span>дней осталось</span></div>
                <div className="subscription-progress" aria-label={active ? `Осталось ${days} дней` : 'Подписка не активна'}><i style={{ width: active ? `${Math.min(100, Math.max(7, days / 3.65))}%` : '0%' }} /><span>{active ? 'сейчас' : '—'}</span><span>{active ? formatDate(access!.expires_at) : '—'}</span></div>
                <p className="subscription-hint">{active ? 'Статус обновляется из Remnawave при каждом открытии' : 'Срок появится после подключения тарифа'}</p>
              </article>
              <article className="traffic-card">
                <header><div><p>Потраченный трафик</p><small>{traffic?.source_status === 'fresh' ? 'обновлено сейчас' : 'последние доступные данные'}</small></div><span>{traffic?.year ?? new Date().getFullYear()} год</span></header>
                <div className="traffic-value" aria-live="polite"><strong>{formatBytes(shownUsage)}</strong><small>за {monthNames[shownMonth - 1]}{shownMonth === currentMonth ? ' · текущий месяц' : ''}</small></div>
                <div className="traffic-bars" aria-label={`Трафик по месяцам за ${traffic?.year ?? new Date().getFullYear()} год`}>
                  {monthLetters.map((letter, index) => {
                    const month = traffic?.months[index]
                    const future = index + 1 > currentMonth
                    return <button key={index} type="button" disabled={future || !month?.has_data} className={`${shownMonth === index + 1 ? 'is-selected' : ''} ${currentMonth === index + 1 ? 'is-current' : ''} ${future ? 'is-future' : ''}`} onClick={() => setSelectedMonth(index + 1)} aria-label={monthNames[index]} aria-pressed={shownMonth === index + 1}><i style={{ height: month?.has_data ? `${Math.max(8, month.used_bytes / maxUsage * 100)}%` : '3px' }} /><span>{letter}</span></button>
                  })}
                </div>
                {liveError && <small className="live-data-error">{liveError}</small>}
              </article>
              <button className="device-line" onClick={() => navigate('devices')}><span className="mini-icon"><Icon name="devices" /></span><span><small>Ваши устройства</small><strong>{devices.length} подключено</strong></span><Icon name="arrow" /></button>
            </aside>
          </div>
        </section>

        <section className={`screen ${view === 'plans' ? 'is-visible' : ''}`}>
          <header className="page-title"><p className="kicker">Тарифы</p><h2>Выберите свой<br />ритм.</h2><p>Пять устройств и безлимитный трафик включены.</p></header>
          {sortedPlans.length ? <div className="plans-grid">{sortedPlans.map((plan) => <button key={plan.id} className={`tariff-card ${planCardClass(plan)}`} data-bg={planBackground(plan)} data-discount={discount(plan.duration_days) ?? undefined} onClick={() => { setPaymentPlan(plan); setPayment(null); setPaymentError(null) }}><span>{planLabel(plan.duration_days)}</span><strong>{formatMoney(plan.price_minor, plan.currency)}</strong><small>{plan.duration_days >= 60 ? `${formatMoney(monthlyPriceMinor(plan), plan.currency)} в месяц` : plan.description}</small><i><Icon name="arrow" /></i></button>)}</div> : <div className="empty-state">Тарифы временно недоступны. Попробуйте обновить кабинет.</div>}
        </section>

        <section className={`screen ${view === 'devices' ? 'is-visible' : ''}`}>
          <header className="page-title compact"><p className="kicker">Подключения</p><div className="device-title-row"><h2>Устройства</h2><button className="circle-action" onClick={() => setModal(access?.subscription_url ? { kicker: 'Новое устройство', title: 'Добавьте подписку.', copy: 'Скопируйте персональную ссылку и импортируйте её в Happ или v2RayTun.', action: 'Скопировать ссылку', onAction: copyAccess } : { kicker: 'Новое устройство', title: 'Сначала нужен тариф.', copy: 'После оплаты персональная ссылка появится здесь автоматически.', action: 'Выбрать тариф', onAction: () => { setModal(null); navigate('plans') } })} aria-label="Добавить устройство"><Icon name="plus" /></button></div></header>
          <div className="timeline">
            {devices.map((device, index) => <button className={`timeline-row ${index === 0 ? 'active' : ''}`} key={device.hardware_id} onClick={() => setModal({ kicker: 'Устройство', title: shortDeviceName(device), copy: device.last_seen_at ? `Последняя активность: ${formatDate(device.last_seen_at)}. Можно отвязать устройство от подписки.` : 'Устройство зарегистрировано в Remnawave.', action: 'Удалить устройство', onAction: () => removeDevice(device) })}><span className="timeline-node" /><small>{index === 0 ? 'Сейчас' : device.last_seen_at ? new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit' }).format(new Date(device.last_seen_at)) : 'Недавно'}</small><div><span className="device-art"><Icon name={deviceIcon(device)} /></span><p><strong>{shortDeviceName(device)}</strong><small>{device.platform || 'Платформа не определена'}</small></p>{index === 0 ? <b>Активно</b> : <Icon name="chevron" />}</div></button>)}
            {Array.from({ length: Math.max(1, limit - devices.length) }, (_, index) => <button className="timeline-row empty" key={`free-${index}`} onClick={() => setModal(access?.subscription_url ? { kicker: 'Свободное место', title: 'Подключите устройство.', copy: 'Скопируйте персональную ссылку и импортируйте её в совместимое приложение.', action: 'Скопировать ссылку', onAction: copyAccess } : { kicker: 'Подключение', title: 'Нет активного тарифа.', copy: 'Выберите тариф, чтобы получить персональную ссылку.' })}><span className="timeline-node" /><small>Свободно</small><div><span className="device-art"><Icon name="plus" /></span><p><strong>Добавить устройство</strong><small>Доступно ещё {Math.max(0, limit - devices.length)}</small></p><Icon name="chevron" /></div></button>)}
          </div>
        </section>

        <section className={`screen ${view === 'support' ? 'is-visible' : ''}`}>
          <header className="page-title"><p className="kicker">Поддержка</p><h2>Мы рядом,<br />когда нужно.</h2></header>
          <div className="support-grid">
            <button className="contact-card" onClick={() => setModal({ kicker: 'Поддержка', title: 'Напишите оператору.', copy: 'Опишите устройство, приложение и что именно происходит. Так мы быстрее найдём причину.', action: 'Открыть Telegram', onAction: () => { if (window.Telegram?.WebApp.openLink) window.Telegram.WebApp.openLink('https://t.me/rovynBot'); else window.open('https://t.me/rovynBot', '_blank', 'noopener,noreferrer') } })}><span>Написать оператору</span><strong>Среднее время<br />ответа — 3 минуты</strong><i><Icon name="arrow" /></i></button>
            <div className="questions">
              <FaqButton index="01" title="VPN не подключается" copy="Проверьте интернет без VPN, затем обновите подписку в приложении и попробуйте другой профиль. Если не помогло — пришлите оператору название профиля и приложения." setModal={setModal} />
              <FaqButton index="02" title="Как установить VPN?" copy="На странице «Устройства» нажмите плюс, скопируйте персональную ссылку и импортируйте её в Happ или v2RayTun." setModal={setModal} />
              <FaqButton index="03" title="Интернет стал медленнее" copy="Смените серверный профиль, отключите ограничение энергосбережения и сравните скорость в одной сети. Передайте оператору результаты двух замеров." setModal={setModal} />
            </div>
          </div>
        </section>

        <section className={`screen ${view === 'profile' ? 'is-visible' : ''}`}>
          <header className="profile-title">
            <p className="kicker">Профиль</p>
            <div className="profile-identity-row">
              <div className="profile-orbit"><span>{telegramPhoto ? <img src={telegramPhoto} alt="" /> : initials(displayName)}</span></div>
              <div className="profile-identity-copy"><h2>{displayName}</h2><small>ID {me.user.telegram_id ?? me.user.id}</small></div>
            </div>
          </header>
          <div className="profile-grid">
            <article className="account-card"><p className="kicker">Способы входа</p><button onClick={() => setModal({ kicker: 'Email', title: 'Скоро появится.', copy: 'Сейчас основным способом входа остаётся Telegram.' })}><Icon name="mail" /><span><small>Email</small><strong>Не подключён</strong></span><Icon name="chevron" /></button><button onClick={() => setModal({ kicker: 'Способ входа', title: 'Telegram подключён.', copy: 'Профиль защищён подписью Telegram Mini App. Email-вход будет добавлен отдельно.' })}><Icon name="telegram" /><span><small>Telegram</small><strong>{embedded ? 'Подключён' : 'Браузерная сессия'}</strong></span><b>✓</b></button></article>
            <article className="settings-card"><p className="kicker">Настройки</p><button onClick={() => setNotifications((value) => !value)}><span>Уведомления</span><small>{notifications ? 'Включены' : 'Выключены'}</small></button><button onClick={() => setModal({ kicker: 'Язык', title: 'Русский.', copy: 'Другие языки будут доступны в следующих версиях.' })}><span>Язык</span><small>Русский</small></button><button onClick={() => setModal({ kicker: 'Сессия', title: 'Закрыть кабинет?', copy: 'Для завершения сессии закройте Mini App или вкладку браузера.', action: 'Закрыть', onAction: () => window.Telegram?.WebApp.close?.() })}><span>Выйти</span><Icon name="arrow" /></button></article>
          </div>
        </section>

        {isOwner && <section className={`screen ${view === 'admin' ? 'is-visible' : ''}`}>
          <header className="page-title admin-page-title"><p className="kicker">Пользователи</p><h2>Выдать доступ</h2></header>
          <div className="admin-preview-layout">
            <section className="admin-preview-panel admin-preview-search">
              <label><span>Telegram ID</span><input inputMode="numeric" value={adminTelegramId} onChange={(event) => setAdminTelegramId(event.target.value.replace(/\D/g, ''))} placeholder="Введите ID пользователя" /></label>
              <button type="button" disabled={adminBusy} onClick={() => void searchAdminUser()}>{adminBusy ? 'Ищем…' : 'Найти'}</button>
              {adminUser && <div className="admin-preview-user"><span className="admin-preview-avatar">{initials(adminUser.display_name || 'Новый пользователь')}</span><p><small>Telegram ID{adminUser.username ? ` · @${adminUser.username}` : ''}</small><strong>{adminUser.display_name || 'Новый пользователь'}</strong><small>{adminUser.found ? adminUser.subscription ? `${adminUser.subscription.plan_name} · до ${formatDate(adminUser.subscription.expires_at)}` : 'Профиль найден, подписки нет' : 'Профиль будет создан при выдаче'}</small></p><b>{adminUser.remnawave_linked ? 'Связан' : adminUser.found ? 'Без VPN' : 'Новый'}</b></div>}
            </section>
            <section className="admin-preview-panel admin-preview-form">
              <h3>Параметры подписки</h3>
              <label><span>Тариф</span><select value={adminPlanId} onChange={(event) => setAdminPlanId(event.target.value)}>{sortedPlans.map((plan) => <option value={plan.id} key={plan.id}>{plan.name} · {formatMoney(plan.price_minor, plan.currency)}</option>)}</select></label>
              <label><span>Устройства</span><select value={adminDeviceLimit} onChange={(event) => setAdminDeviceLimit(event.target.value)}><option value="5">До 5 устройств</option><option value="10">До 10 устройств</option></select></label>
              <label><span>Начало</span><input type="date" max={new Date().toISOString().slice(0, 10)} value={adminStartsOn} onChange={(event) => setAdminStartsOn(event.target.value)} /></label>
              <label><span>Комментарий</span><input value={adminComment} maxLength={240} onChange={(event) => setAdminComment(event.target.value)} /></label>
              <div className="admin-preview-total"><span>Сумма ручной выдачи</span><strong>{adminPlan ? formatMoney(adminPlan.price_minor, adminPlan.currency) : '—'}</strong></div>
              {adminError && <p className="admin-preview-message is-error" role="alert">{adminError}</p>}
              {adminResult && <p className="admin-preview-message is-success">Доступ выдан до {formatDate(adminResult.expires_at)}{adminResult.subscription_url ? ' · ссылка создана' : ''}</p>}
              <button className="admin-preview-submit" type="button" disabled={adminBusy || !adminPlanId || !adminTelegramId} onClick={() => void submitAdminGrant()}>{adminBusy ? 'Выполняем…' : 'Создать и выдать доступ'} <Icon name="arrow" /></button>
            </section>
          </div>
        </section>}
      </main>

      <nav className="dock" aria-label="Основная навигация">
        <NavButton name="home" icon="home" label="Главная" active={view === 'home'} navigate={navigate} />
        <NavButton name="plans" icon="plans" label="Тарифы" active={view === 'plans'} navigate={navigate} />
        <NavButton name="devices" icon="devices" label="Устройства" active={view === 'devices'} navigate={navigate} />
        {!isOwner && <NavButton name="support" icon="support" label="Поддержка" active={view === 'support'} navigate={navigate} />}
        <NavButton name="profile" icon="profile" label="Профиль" active={view === 'profile'} navigate={navigate} />
        {isOwner && <NavButton name="admin" icon="admin" label="Админка" active={view === 'admin'} navigate={navigate} />}
      </nav>

      {paymentPlan && <PaymentModal plan={paymentPlan} payment={payment} busy={paymentBusy} error={paymentError} close={closePayment} closing={modalClosing} submit={startPayment} refocus={modalRef} />}
      {modal && <ActionModal modal={modal} close={closeAction} closing={modalClosing} refocus={modalRef} />}
    </>
  )
}

function NavButton({ name, icon, label, active, navigate }: { name: CabinetView; icon: string; label: string; active: boolean; navigate: (view: CabinetView) => void }) {
  return <button className={`nav-item ${active ? 'is-active' : ''}`} data-tip={label} aria-label={label} onClick={() => navigate(name)}><Icon name={icon} /></button>
}

function FaqButton({ index, title, copy, setModal }: { index: string; title: string; copy: string; setModal: (value: ModalState) => void }) {
  return <button onClick={() => setModal({ kicker: 'Быстрый ответ', title, copy })}><i>{index}</i><span>{title}</span><Icon name="arrow" /></button>
}

function PaymentModal({ plan, payment, busy, error, close, closing, submit, refocus }: { plan: Plan; payment: CheckoutOrder | null; busy: boolean; error: string | null; close: () => void; closing: boolean; submit: () => void; refocus: React.MutableRefObject<HTMLElement | null> }) {
  const paid = payment?.status === 'paid' || payment?.payment_status === 'succeeded'
  return <div className={`payment-layer is-open ${closing ? 'is-closing' : ''}`}><button className="payment-scrim" type="button" onClick={close} aria-label="Закрыть оплату" /><section className="payment-sheet modal-surface" role="dialog" aria-modal="true" aria-labelledby="payment-title" tabIndex={-1} ref={(node) => { refocus.current = node }}><div className="modal-grabber" aria-hidden="true"><i /></div><div className="modal-toolbar"><span className="modal-brand">N</span><div className="payment-steps"><span className="is-current">01</span><i /><span>02</span></div><button className="modal-close" onClick={close} aria-label="Закрыть оплату"><Icon name="close" /></button></div><div className="modal-intro"><p className="kicker">Подключение тарифа</p><h2>{paid ? 'Готово.' : 'Почти готово.'}</h2></div><div className="payment-plan-summary"><div><small>Выбранный тариф</small><strong id="payment-title">{plan.name}</strong></div><strong>{formatMoney(plan.price_minor, plan.currency)}</strong></div><div className="payment-method"><span className="sbp-mark">СБП</span><div><strong>Система быстрых платежей</strong><small>YooKassa · без сохранения карты</small></div><b>✓</b></div><div className="payment-benefits"><span>{formatTrafficLimit(plan.traffic_limit_bytes)} трафика</span><span>До {plan.device_limit} устройств</span><span>Активация сразу</span></div>{error && <p className="modal-error" role="alert">{error}</p>}<div className="modal-actions"><button className={`payment-submit ${busy ? 'is-loading' : ''}`} disabled={busy || paid} onClick={submit}>{paid ? 'Подписка оплачена' : payment ? 'Открыть оплату ещё раз' : 'Оплатить через СБП'} <Icon name="arrow" /></button><button className="modal-secondary" onClick={close}>Вернуться к тарифам</button></div><small className="modal-note">Платёж создаётся в YooKassa. Данные карты не сохраняются в NOVA.</small></section></div>
}

function ActionModal({ modal, close, closing, refocus }: { modal: NonNullable<ModalState>; close: () => void; closing: boolean; refocus: React.MutableRefObject<HTMLElement | null> }) {
  async function run() {
    if (modal.onAction) await modal.onAction()
    else close()
  }
  return <div className={`action-layer is-open ${closing ? 'is-closing' : ''}`}><button className="action-scrim" type="button" onClick={close} aria-label="Закрыть окно" /><section className="action-sheet modal-surface" role="dialog" aria-modal="true" aria-labelledby="action-title" tabIndex={-1} ref={(node) => { refocus.current = node }}><div className="modal-grabber" aria-hidden="true"><i /></div><div className="modal-toolbar"><span className="modal-brand">N</span><span className="modal-context">Сервис NOVA</span><button className="modal-close" onClick={close} aria-label="Закрыть окно"><Icon name="close" /></button></div><div className="action-sheet__content"><p className="kicker">{modal.kicker}</p><h2 id="action-title">{modal.title}</h2><p>{modal.copy}</p></div><div className="modal-actions">{modal.action && <button className="action-primary" onClick={() => void run()}>{modal.action} <Icon name="arrow" /></button>}<button className="modal-secondary" onClick={close}>Закрыть</button></div></section></div>
}
