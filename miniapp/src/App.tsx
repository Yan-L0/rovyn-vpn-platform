/* Legacy cabinet components below are intentionally retained for rollback during the v2 rollout. */
/* eslint-disable @typescript-eslint/no-unused-vars */
import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from 'react'
import {
  ArrowLeft,
  ArrowRight,
  Bell,
  Check,
  ChevronRight,
  Chrome,
  CircleHelp,
  Copy,
  Download,
  ExternalLink,
  FileText,
  Gift,
  Globe2,
  Headphones,
  House,
  Laptop,
  LoaderCircle,
  LogOut,
  Mail,
  Menu,
  MonitorSmartphone,
  Paperclip,
  Plus,
  Radio,
  RotateCw,
  Send,
  ShieldCheck,
  Smartphone,
  Sparkles,
  Settings,
  TabletSmartphone,
  Tv,
  WalletCards,
  Wifi,
  X,
  Zap,
} from 'lucide-react'
import {
  authenticate,
  createSbpOrder,
  loadDevices,
  loadMe,
  loadOrder,
  loadPlans,
  loadSubscriptionAccess,
  loadYearlyTraffic,
  revokeDevice,
  type CheckoutOrder,
  type Device,
  type Me,
  type Plan,
  type SubscriptionAccess,
  type YearlyUsage,
} from './api'
import CabinetV2 from './CabinetV2'

type View = 'dashboard' | 'plans' | 'connect' | 'devices' | 'referral' | 'analytics' | 'wallet' | 'support' | 'chat' | 'legal'

const supportedViews = new Set<View>([
  'dashboard', 'plans', 'connect', 'devices', 'referral', 'analytics', 'wallet', 'support', 'chat', 'legal',
])

// Outside Telegram, use the official Mini App deep-link so Telegram opens the
// cabinet in its fullscreen Web App surface. Inside Telegram, keep navigation
// on the HTTPS app URL to avoid leaving the current Mini App session.
const appUrl = (import.meta.env.VITE_TELEGRAM_BOT_URL as string | undefined) ?? '/cabinet?app=1'
const launchUrl = (import.meta.env.VITE_TELEGRAM_LAUNCH_URL as string | undefined) ?? appUrl
const productUrl = launchUrl
const cabinetUrl = launchUrl

function initialView(): View {
  const value = window.location.hash.replace('#', '') as View
  return supportedViews.has(value) ? value : 'dashboard'
}

function isMiniAppMode(): boolean {
  const params = new URLSearchParams(window.location.search)
  return window.location.pathname.startsWith('/cabinet')
    || params.get('app') === '1'
    || params.has('tgWebAppVersion')
    || Boolean(window.Telegram?.WebApp.initData)
}

function isTelegramEmbedded(): boolean {
  const params = new URLSearchParams(window.location.search)
  return params.has('tgWebAppVersion') || Boolean(window.Telegram?.WebApp.initData)
}

function formatMoney(value: number, currency: string): string {
  return new Intl.NumberFormat('ru-RU', {
    style: 'currency', currency, maximumFractionDigits: 0,
  }).format(value / 100)
}

function formatBytes(value: number | null): string {
  if (value === null) return '—'
  if (value < 1024) return `${value} Б`
  const units = ['КБ', 'МБ', 'ГБ', 'ТБ']
  let amount = value / 1024
  let index = 0
  while (amount >= 1024 && index < units.length - 1) {
    amount /= 1024
    index += 1
  }
  return `${new Intl.NumberFormat('ru-RU', { maximumFractionDigits: amount >= 10 ? 1 : 2 }).format(amount)} ${units[index]}`
}

function maskSubscriptionUrl(value: string): string {
  try {
    const parsed = new URL(value)
    const firstSegment = parsed.pathname.split('/').filter(Boolean)[0]
    return `${parsed.origin}/${firstSegment ? `${firstSegment}/` : ''}••••••••`
  } catch {
    return 'Персональная ссылка VPN'
  }
}

function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <span className={`brand ${compact ? 'compact' : ''}`} aria-label="NOVA VPN">
      <span className="brand-symbol"><span /><span /></span>
      {!compact && <span>NOVA</span>}
    </span>
  )
}

export default function App() {
  const miniAppMode = isMiniAppMode()
  useEffect(() => {
    document.body.classList.toggle('cabinet-body', miniAppMode)
    const themeColor = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')
    themeColor?.setAttribute('content', miniAppMode ? '#0b302d' : '#050706')
    return () => {
      document.body.classList.remove('cabinet-body')
      themeColor?.setAttribute('content', '#050706')
    }
  }, [miniAppMode])
  return miniAppMode ? <MiniApp /> : <PublicSite />
}

function PublicSite() {
  const [plans, setPlans] = useState<Plan[]>([])
  const [plansLoading, setPlansLoading] = useState(true)
  const [menuOpen, setMenuOpen] = useState(false)

  useEffect(() => {
    loadPlans()
      .then(setPlans)
      .catch(() => setPlans([]))
      .finally(() => setPlansLoading(false))
  }, [])

  const closeMenu = () => setMenuOpen(false)

  return (
    <div className="public-site">
      <header className="site-header">
        <a href="#top" className="brand-link" aria-label="NOVA VPN — на главную"><Brand /></a>
        <nav className={menuOpen ? 'open' : ''} aria-label="Основная навигация">
          <a href="#advantages" onClick={closeMenu}>Возможности</a>
          <a href="#how" onClick={closeMenu}>Подключение</a>
          <a href="#pricing" onClick={closeMenu}>Тарифы</a>
          <a href="#faq" onClick={closeMenu}>Вопросы</a>
        </nav>
        <a className="header-action" href={cabinetUrl}>
          <span className="telegram-dot">↗</span> Кабинет
        </a>
        <button className="menu-button" onClick={() => setMenuOpen((value) => !value)} aria-label="Открыть меню">
          {menuOpen ? <X /> : <Menu />}
        </button>
      </header>

      <main id="top">
        <section className="landing-hero">
          <div className="hero-copy">
            <div className="live-badge"><i /> Единый кабинет <span>Сайт + Telegram</span></div>
            <h1>Интернет<br /><em>без лишних</em><br />ограничений</h1>
            <p>Одна подписка для телефона и компьютера. Получите персональную ссылку в Telegram и подключитесь через Happ или v2RayTun.</p>
            <div className="hero-actions">
              <a className="button button-light" href={productUrl}>Попробовать <ArrowRight /></a>
              <a className="button button-ghost" href="#how">Как подключиться</a>
            </div>
            <div className="hero-note"><ShieldCheck /> Управление подпиской и устройствами в одном месте</div>
          </div>

          <div className="hero-visual" aria-label="Пример личного кабинета NOVA VPN">
            <div className="glow-orbit orbit-one" />
            <div className="glow-orbit orbit-two" />
            <div className="floating-chip chip-speed"><Wifi /><span><small>Соединение</small><strong>Защищено</strong></span></div>
            <div className="floating-chip chip-device"><Smartphone /><span><small>Устройства</small><strong>До 10</strong></span></div>
            <div className="phone-frame">
              <div className="phone-top"><Brand compact /><span>•••</span></div>
              <div className="phone-status">
                <div className="mini-shield"><ShieldCheck /></div>
                <small>СТАТУС ЗАЩИТЫ</small>
                <strong>VPN активен</strong>
                <span>Защищённое соединение</span>
              </div>
              <div className="phone-metrics">
                <span><Globe2 /><small>Маршрут</small><strong>Авто</strong></span>
                <span><Zap /><small>Режим</small><strong>Быстрый</strong></span>
              </div>
              <button>Подключить устройство <ArrowRight /></button>
            </div>
          </div>
        </section>

        <div className="trust-row" aria-label="Преимущества сервиса">
          <span><strong>01</strong> Единая подписка</span>
          <span><strong>02</strong> Happ + v2RayTun</span>
          <span><strong>03</strong> Telegram Mini App</span>
          <span><strong>04</strong> Управление устройствами</span>
        </div>

        <section className="landing-section" id="advantages">
          <div className="section-heading split">
            <div><span className="section-kicker">ПОЧЕМУ NOVA</span><h2>Просто пользоваться.<br />Легко управлять.</h2></div>
            <p>Мы убрали регистрацию, длинные настройки и отдельные личные кабинеты. Всё управление находится в привычном Telegram.</p>
          </div>
          <div className="feature-grid">
            <article className="feature-card feature-wide">
              <span className="feature-number">01</span><Radio />
              <h3>Подключение в несколько нажатий</h3>
              <p>Выберите тариф, установите приложение и импортируйте персональную ссылку.</p>
              <div className="signal-lines"><i /><i /><i /><i /></div>
            </article>
            <article className="feature-card"><span className="feature-number">02</span><Globe2 /><h3>Умные маршруты</h3><p>Серверные группы назначаются автоматически по вашему тарифу.</p></article>
            <article className="feature-card"><span className="feature-number">03</span><MonitorSmartphone /><h3>Все устройства</h3><p>iOS, Android, macOS и Windows в одной подписке.</p></article>
            <article className="feature-card feature-accent"><span className="feature-number">04</span><Sparkles /><h3>Один дизайн</h3><p>Сайт и Telegram-кабинет говорят на одном языке и всегда показывают актуальные данные.</p></article>
          </div>
        </section>

        <section className="landing-section how-section" id="how">
          <div className="section-heading centered">
            <span className="section-kicker">БЫСТРЫЙ СТАРТ</span>
            <h2>Три шага до подключения</h2>
            <p>Никаких ручных конфигураций и сложных инструкций.</p>
          </div>
          <div className="steps-grid">
            <article><span>1</span><div className="step-icon"><Zap /></div><h3>Выберите тариф</h3><p>Оплатите подходящий период в защищённом кабинете.</p></article>
            <article><span>2</span><div className="step-icon"><Smartphone /></div><h3>Установите клиент</h3><p>Используйте Happ или v2RayTun для своего устройства.</p></article>
            <article><span>3</span><div className="step-icon"><ShieldCheck /></div><h3>Импортируйте ссылку</h3><p>Персональная подписка добавится в приложение автоматически.</p></article>
          </div>
        </section>

        <section className="landing-section pricing-section" id="pricing">
          <div className="section-heading split">
            <div><span className="section-kicker">ТАРИФЫ</span><h2>Честная цена.<br />Никакой рекламы.</h2></div>
            <p>Цены на сайте и в Telegram загружаются из единого каталога — они всегда совпадают.</p>
          </div>
          {plansLoading ? (
            <div className="plans-state"><LoaderCircle className="spinner" /> Загружаем актуальные тарифы…</div>
          ) : plans.length === 0 ? (
            <div className="plans-state">Каталог временно недоступен. Тарифы можно посмотреть в Telegram.</div>
          ) : (
            <div className="public-plans">
              {plans.map((plan, index) => (
                <article className={index === 1 ? 'featured' : ''} key={plan.id}>
                  {index === 1 && <span className="popular-label">ПОПУЛЯРНЫЙ</span>}
                  <span className="plan-name">{plan.name}</span>
                  <div className="plan-price">{formatMoney(plan.price_minor, plan.currency)}<small> / {plan.duration_days} дней</small></div>
                  <p>{plan.description}</p>
                  <ul>
                    <li><Check /> {formatBytes(plan.traffic_limit_bytes)} трафика</li>
                    <li><Check /> До {plan.device_limit} устройств</li>
                    <li><Check /> Happ и v2RayTun</li>
                    <li><Check /> Серверные группы: {plan.server_groups.length}</li>
                  </ul>
                  <a className="button" href={cabinetUrl}>Выбрать тариф <ArrowRight /></a>
                </article>
              ))}
            </div>
          )}
        </section>

        <section className="landing-section faq-section" id="faq">
          <div className="section-heading centered"><span className="section-kicker">ВОПРОСЫ</span><h2>Всё важное перед стартом</h2></div>
          <div className="faq-list">
            <details><summary>Нужно ли регистрироваться?<ChevronRight /></summary><p>Нет. При запуске через Telegram профиль создаётся автоматически на основе защищённых данных Mini App.</p></details>
            <details><summary>Какие приложения поддерживаются?<ChevronRight /></summary><p>Первая версия рассчитана на Happ и v2RayTun. Конкретная кнопка импорта зависит от вашей операционной системы.</p></details>
            <details><summary>Можно использовать на нескольких устройствах?<ChevronRight /></summary><p>Да. Допустимое количество устройств указано в каждом тарифе и контролируется сервером.</p></details>
            <details><summary>Где управлять подпиской?<ChevronRight /></summary><p>В Telegram Mini App: там доступны тариф, срок действия, устройства, подключение и поддержка.</p></details>
          </div>
        </section>

        <section className="final-cta">
          <div className="cta-glow" />
          <Brand />
          <h2>Ваш интернет.<br /><em>Ваши правила.</em></h2>
          <p>Откройте NOVA в Telegram и подготовьте первое устройство к подключению.</p>
          <a className="button button-light" href={productUrl}>Открыть NOVA <ArrowRight /></a>
        </section>
      </main>

      <footer className="site-footer">
        <div><Brand /><p>Управляемая VPN-подписка для ваших устройств.</p></div>
        <div><strong>Продукт</strong><a href="#advantages">Возможности</a><a href="#pricing">Тарифы</a><a href="#how">Подключение</a></div>
        <div><strong>Помощь</strong><a href="#faq">Вопросы</a><a href={productUrl}>Поддержка в Telegram</a></div>
        <div className="footer-meta"><span>© 2026 NOVA VPN</span><span>Первая версия продукта</span></div>
      </footer>
    </div>
  )
}

function MiniApp() {
  return <CabinetV2 />
}

function RailButton({ active, icon, label, onClick }: { active: boolean; icon: ReactNode; label: string; onClick: () => void }) {
  return <button className={active ? 'active' : ''} type="button" onClick={onClick} aria-label={label}>{icon}<span>{label}</span></button>
}

function BrowserAuth() {
  const [showTelegram, setShowTelegram] = useState(false)
  const [emailNotice, setEmailNotice] = useState<string | null>(null)

  useEffect(() => {
    document.body.classList.add('auth-body')
    const themeColor = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')
    themeColor?.setAttribute('content', '#080d0b')
    return () => {
      document.body.classList.remove('auth-body')
      themeColor?.setAttribute('content', '#050706')
    }
  }, [])

  function requestEmail(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setEmailNotice('Вход по email станет доступен после подключения почтового сервиса.')
  }

  return (
    <main className="auth-screen">
      <div className="auth-glow auth-glow-main" />
      <div className="auth-glow auth-glow-side" />
      <a className="auth-logo" href="/" aria-label="NOVA VPN — на главную"><Brand /></a>
      <section className="auth-card" aria-labelledby="auth-title">
        <div className="auth-card-shine" />
        <h1 id="auth-title">Добро пожаловать</h1>
        <p>Войдите в NOVA с помощью</p>
        <form onSubmit={requestEmail}>
          <label className="sr-only" htmlFor="auth-email">Email</label>
          <div className="auth-email-field">
            <input id="auth-email" type="email" autoComplete="email" placeholder="Введите email" required onChange={() => setEmailNotice(null)} />
            <button type="submit" aria-label="Продолжить с email"><ArrowRight /></button>
          </div>
        </form>
        {emailNotice && <div className="auth-notice" role="status">{emailNotice}</div>}
        {!showTelegram ? (
          <button className="auth-more" type="button" onClick={() => setShowTelegram(true)} aria-expanded="false">Другие способы входа</button>
        ) : (
          <div className="auth-alternatives">
            <div className="auth-divider"><span>или</span></div>
            <a className="telegram-login" href={productUrl}>
              <span><Send /></span><strong>Войти через Telegram</strong><ArrowRight />
            </a>
          </div>
        )}
      </section>
      <footer className="auth-footer"><ShieldCheck /> Защищённый вход в NOVA VPN</footer>
    </main>
  )
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', year: 'numeric' })
    .format(new Date(value))
    .replace('.', '')
}

function Dashboard({ me, access, traffic, devices, liveError, onNavigate }: {
  me: Me
  access: SubscriptionAccess | null
  traffic: YearlyUsage | null
  devices: Device[]
  liveError: string | null
  onNavigate: (view: View) => void
}) {
  const subscription = me.subscription
  const providerActive = access?.provider_status === 'active'
  const expiry = access?.expires_at ?? subscription?.expires_at
  const maximum = Math.max(...(traffic?.months.map((month) => month.used_bytes) ?? [0]), 1)
  const monthNames = ['Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн', 'Июл', 'Авг', 'Сен', 'Окт', 'Ноя', 'Дек']
  return (
    <section className="reference-home">
      <div className={`subscription-notice ${providerActive ? 'active' : ''}`}>
        <span aria-hidden="true">{providerActive ? <Check /> : <Zap />}</span>
        <p>{providerActive && expiry ? `Подписка NOVA активна до ${formatDate(expiry)}` : subscription ? 'Проверяем состояние подписки' : 'Продлите подписку, чтобы снова получить доступ ко всем функциям NOVA'}</p>
      </div>
      <div className="reference-account">
        <Brand />
        <span className="reference-balance"><small>Баланс</small><strong>{formatMoney(me.wallet_balance_minor, me.wallet_currency)}</strong></span>
        <span className={`reference-status ${access?.provider_status === 'active' ? 'active' : ''}`}><i />{access ? `VPN: ${access.provider_status === 'active' ? 'активен' : access.provider_status}` : subscription ? 'Получаем статус VPN' : 'Подписка закончилась'}</span>
        <div className="reference-chips">
          <span>{access ? `${devices.length} из ${access.device_limit} устройств` : 'Устройства недоступны'}</span>
          <span>{access ? access.plan_name : 'Тариф недоступен'}</span>
        </div>
        <button className="reference-primary" type="button" onClick={() => onNavigate('plans')}><WalletCards />{subscription ? 'Продлить подписку' : 'Оплатить подписку'}</button>
        <button className="reference-outline" type="button" onClick={() => onNavigate('connect')}><Settings />Настроить VPN</button>
        {subscription && (
          <section className="live-usage" aria-label={`Трафик за ${traffic?.year ?? new Date().getFullYear()} год`}>
            <header>
              <div><small>Трафик в текущем месяце</small><strong>{traffic ? formatBytes(traffic.current_month_used_bytes) : '—'}</strong></div>
              <span className={traffic?.source_status === 'fresh' ? 'fresh' : ''}>{traffic?.source_status === 'fresh' ? 'Обновлено сейчас' : traffic ? 'Последние сохранённые данные' : 'Нет данных'}</span>
            </header>
            <div className="year-bars">
              {(traffic?.months ?? Array.from({ length: 12 }, (_, index) => ({ month: index + 1, used_bytes: 0, has_data: false }))).map((month) => (
                <div className={month.month === traffic?.current_month ? 'current' : ''} key={month.month} title={month.has_data ? `${monthNames[month.month - 1]}: ${formatBytes(month.used_bytes)}` : `${monthNames[month.month - 1]}: данных пока нет`}>
                  <i style={{ height: month.has_data ? `${Math.max(7, (month.used_bytes / maximum) * 100)}%` : '3px' }} />
                  <small>{monthNames[month.month - 1]}</small>
                </div>
              ))}
            </div>
            <footer><span>{traffic?.year ?? new Date().getFullYear()} · 12 месяцев</span><button type="button" onClick={() => onNavigate('devices')}>{devices.length} устройств <ArrowRight /></button></footer>
            {liveError && <p className="live-data-error" role="status">Не все данные обновились: {liveError}</p>}
          </section>
        )}
        <div className="reference-feature-cards">
          <button type="button" onClick={() => onNavigate('referral')}>
            <strong>Пригласи друга</strong><span className="feature-art gift-art"><Gift /></span><i><ArrowRight /></i>
          </button>
          <button type="button" onClick={() => onNavigate('support')}>
            <strong>Поддержка</strong><span className="feature-art support-art"><Headphones /></span><i><ArrowRight /></i>
          </button>
        </div>
      </div>
    </section>
  )
}

function planPeriod(days: number): { count: string; label: string } {
  if (days >= 360) return { count: String(Math.round(days / 365)), label: 'год' }
  if (days >= 60) return { count: String(Math.round(days / 30)), label: 'месяца' }
  if (days >= 28) return { count: String(Math.round(days / 30)), label: 'месяц' }
  return { count: String(days), label: 'дней' }
}

function Plans({ plans, browserCheckout, onBack }: { plans: Plan[]; browserCheckout: boolean; onBack: () => void }) {
  const catalog = plans.slice().sort((a, b) => b.duration_days - a.duration_days)
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [carouselOffset, setCarouselOffset] = useState(0)
  const [checkout, setCheckout] = useState<CheckoutOrder | null>(null)
  const [checkoutLoading, setCheckoutLoading] = useState(false)
  const [checkoutError, setCheckoutError] = useState<string | null>(null)
  const selected = catalog[Math.min(selectedIndex, catalog.length - 1)]
  const durationDays = selected?.duration_days ?? 30
  const periodMonths = Math.max(1, Math.round(durationDays / 30))
  const perMonthMinor = Math.round((selected?.price_minor ?? 0) / periodMonths)
  const perDayMinor = Math.round((selected?.price_minor ?? 0) / Math.max(1, durationDays))
  const discountFor = (days: number) => days >= 360 ? '-25%' : days >= 170 ? '-16%' : days >= 80 ? '-10%' : ''
  const checkoutPaid = checkout?.status === 'paid' || checkout?.payment_status === 'succeeded'
  const checkoutStopped = checkout?.status === 'cancelled'
    || checkout?.status === 'expired'
    || checkout?.status === 'failed'
    || checkout?.payment_status === 'cancelled'
    || checkout?.payment_status === 'failed'

  useEffect(() => {
    setCheckout(null)
    setCheckoutError(null)
  }, [selected?.id])

  useEffect(() => {
    if (!checkout || checkoutPaid || checkoutStopped) return
    const refresh = () => {
      void loadOrder(checkout.order_id)
        .then(setCheckout)
        .catch(() => undefined)
    }
    const timer = window.setInterval(refresh, 5000)
    window.addEventListener('focus', refresh)
    return () => {
      window.clearInterval(timer)
      window.removeEventListener('focus', refresh)
    }
  }, [checkout, checkoutPaid, checkoutStopped])

  async function startCheckout() {
    if (!selected) return
    setCheckoutLoading(true)
    setCheckoutError(null)
    try {
      const idempotencyKey = window.crypto.randomUUID()
      const order = await createSbpOrder(selected.id, idempotencyKey)
      setCheckout(order)
      if (order.confirmation_url) {
        const paymentWindow = window.open(order.confirmation_url, '_blank', 'noopener,noreferrer')
        if (!paymentWindow) window.location.assign(order.confirmation_url)
      }
    } catch (reason) {
      setCheckoutError(reason instanceof Error ? reason.message : 'Не удалось создать платёж')
    } finally {
      setCheckoutLoading(false)
    }
  }

  async function refreshCheckout() {
    if (!checkout) return
    setCheckoutLoading(true)
    setCheckoutError(null)
    try {
      setCheckout(await loadOrder(checkout.order_id))
    } catch (reason) {
      setCheckoutError(reason instanceof Error ? reason.message : 'Не удалось проверить платёж')
    } finally {
      setCheckoutLoading(false)
    }
  }

  if (!selected) {
    return <section className="purchase-screen reference-plans"><PagePill title="Покупка подписки" onBack={onBack} /><div className="cabinet-alert"><ShieldCheck /> Активные тарифы не настроены на сервере.</div></section>
  }

  return (
    <section className="purchase-screen reference-plans">
      <PagePill title="Покупка подписки" onBack={onBack} />
      <header className="catalog-heading">
        <h2>Интернет на ваших условиях</h2>
        <p>Доступ ко всему миру и высокий уровень защиты — в одном тарифе</p>
      </header>
      <div className="plan-carousel-shell">
        <button className="carousel-arrow carousel-prev" type="button" aria-label="Назад" disabled={carouselOffset === 0} onClick={() => setCarouselOffset(0)}><ArrowLeft /></button>
        <div className="plan-carousel-viewport">
          <div className="plan-carousel-track" style={{ transform: `translateX(-${carouselOffset * 174}px)` }} role="radiogroup" aria-label="Тарифы">
            {catalog.map((plan, index) => {
              const period = planPeriod(plan.duration_days)
              const monthly = Math.round(plan.price_minor / Math.max(1, plan.duration_days / 30))
              return (
                <button className={`catalog-plan-card ${index === selectedIndex ? 'selected' : ''}`} type="button" role="radio" aria-checked={index === selectedIndex} key={plan.id} onClick={() => { setSelectedIndex(index); window.Telegram?.WebApp.HapticFeedback?.impactOccurred('light') }}>
                  {discountFor(plan.duration_days) && <em>{discountFor(plan.duration_days)}</em>}
                  <span>{period.count} {period.label}</span>
                  <strong>{formatMoney(plan.price_minor, plan.currency)}</strong>
                  <small>{formatMoney(monthly, plan.currency)} / мес</small>
                </button>
              )
            })}
          </div>
        </div>
        <button className="carousel-arrow carousel-next" type="button" aria-label="Вперёд" disabled={catalog.length <= 2 || carouselOffset > 0} onClick={() => setCarouselOffset(Math.max(0, catalog.length - 2))}><ArrowRight /></button>
      </div>

      <section className="device-count-card included-devices">
        <div>
          <h3>Устройства уже включены</h3>
          <p>Тариф позволяет подключить до {selected.device_limit} устройств без доплаты</p>
        </div>
        <strong>{selected.device_limit}</strong>
      </section>

      <section className="checkout-card">
        <div><span>Период</span><strong>{planPeriod(selected.duration_days).count} {planPeriod(selected.duration_days).label}</strong><small>{formatMoney(perDayMinor, selected.currency)} / день</small></div>
        <div><span>Устройства</span><strong>{selected.device_limit}</strong><small>включено</small></div>
      </section>
      {browserCheckout ? (
        <>
          {!checkoutPaid && !checkoutStopped && (
            <button className="reference-primary checkout-button" type="button" disabled={checkoutLoading} onClick={() => void (checkout?.confirmation_url ? window.open(checkout.confirmation_url, '_blank', 'noopener,noreferrer') : startCheckout())}>
              {checkoutLoading ? <LoaderCircle className="spinner" /> : <WalletCards />}
              {checkout ? 'Перейти к оплате по СБП' : `Оплатить по СБП ${formatMoney(selected.price_minor, selected.currency)}`}
            </button>
          )}
          {checkout && (
            <div className={`checkout-status ${checkoutPaid ? 'success' : checkoutStopped ? 'failed' : 'pending'}`} role="status">
              <span>{checkoutPaid ? <Check /> : checkoutStopped ? <X /> : <LoaderCircle className="spinner" />}</span>
              <div>
                <strong>{checkoutPaid ? 'Подписка оплачена' : checkoutStopped ? 'Платёж не завершён' : 'Ожидаем оплату'}</strong>
                <small>{checkoutPaid ? 'Статус подписки обновится автоматически.' : checkoutStopped ? 'Создайте новый платёж, когда будете готовы.' : 'После оплаты вернитесь на эту страницу.'}</small>
              </div>
              {!checkoutPaid && <button type="button" disabled={checkoutLoading} onClick={() => void (checkoutStopped ? startCheckout() : refreshCheckout())}>{checkoutStopped ? 'Повторить' : 'Проверить'}</button>}
            </div>
          )}
          {checkoutError && <p className="checkout-error" role="alert">{checkoutError}</p>}
          <p className="cabinet-caption">Безопасная оплата через YooKassa · СБП · {formatMoney(perMonthMinor, selected.currency)} в месяц</p>
        </>
      ) : (
        <div className="miniapp-checkout-note">
          <ShieldCheck />
          <div><strong>Управление подпиской в Mini App</strong><p>Здесь можно выбрать тариф и контролировать подписку. Оплата по СБП доступна в защищённой браузерной версии кабинета.</p></div>
        </div>
      )}
    </section>
  )
}

function Connect({ subscriptionUrl, onNavigate }: { subscriptionUrl: string | null; onNavigate: (view: View) => void }) {
  const hasSubscription = Boolean(subscriptionUrl)
  const [mode, setMode] = useState<'where' | 'here' | 'other'>('where')
  const [client, setClient] = useState<'happ' | 'v2ray'>('happ')
  const [platform, setPlatform] = useState<string | null>(null)
  const [showImportHelp, setShowImportHelp] = useState(false)
  const [copied, setCopied] = useState(false)
  const platforms = [
    { id: 'ios', title: 'iOS', note: 'App Store', icon: <Smartphone /> },
    { id: 'android', title: 'Android', note: 'Google Play', icon: <TabletSmartphone /> },
    { id: 'macos', title: 'macOS', note: 'App Store', icon: <Laptop /> },
    { id: 'tv', title: 'TV', note: 'Happ · APK', icon: <Tv /> },
    { id: 'windows', title: 'Windows', note: 'Happ · EXE', icon: <MonitorSmartphone /> },
    { id: 'linux', title: 'Linux', note: 'Happ', icon: <Laptop /> },
    { id: 'chrome', title: 'Chrome', note: 'Расширение', icon: <Chrome /> },
  ]

  const goBack = () => {
    if (platform) setPlatform(null)
    else if (mode !== 'where') setMode('where')
    else onNavigate('dashboard')
  }

  async function copySubscriptionUrl() {
    if (!subscriptionUrl) return
    await navigator.clipboard.writeText(subscriptionUrl)
    setCopied(true)
    window.Telegram?.WebApp.HapticFeedback?.impactOccurred('medium')
    window.setTimeout(() => setCopied(false), 1800)
  }

  if (mode === 'where') {
    return (
      <section className="setup-screen setup-choice-screen">
        <PagePill title="Где настраиваем?" onBack={goBack} />
        <p className="setup-lead">Выберите устройство, на котором требуется настройка</p>
        <div className="setup-choice-list">
          <button className="selected" type="button" onClick={() => setMode('here')}><span><Smartphone /></span><strong>На этом устройстве</strong><Check /></button>
          <button type="button" onClick={() => setMode('other')}><span><MonitorSmartphone /></span><strong>На другом устройстве</strong><ArrowRight /></button>
        </div>
        {!hasSubscription && <div className="cabinet-alert"><ShieldCheck /> Для получения персональной ссылки сначала активируйте подписку</div>}
        <button className="reference-primary setup-next" type="button" onClick={() => setMode('here')}>Настроить на этом устройстве</button>
      </section>
    )
  }

  if (mode === 'here') {
    return (
      <section className="setup-screen app-choice-screen">
        <PagePill title="Какое приложение?" onBack={goBack} />
        <p className="setup-lead">Установите приложение, которое подходит под ваши задачи</p>
        <div className="client-choice-grid">
          <button className={client === 'happ' ? 'selected' : ''} type="button" onClick={() => setClient('happ')}>
            <em>Рекомендуем</em><span className="client-glyph">H</span><strong>Happ</strong><small>Простая установка и быстрый импорт</small><i>{client === 'happ' && <Check />}</i>
          </button>
          <button className={client === 'v2ray' ? 'selected' : ''} type="button" onClick={() => setClient('v2ray')}>
            <em>Поддерживается</em><span className="client-glyph secondary">V</span><strong>v2RayTun</strong><small>Расширенные настройки маршрутов</small><i>{client === 'v2ray' && <Check />}</i>
          </button>
        </div>
        <button className="reference-primary setup-install" type="button" disabled={!hasSubscription}><Download />Установить {client === 'happ' ? 'Happ' : 'v2RayTun'}</button>
        <button className="reference-outline setup-existing" type="button" disabled={!hasSubscription}>У меня уже есть приложение</button>
        {!hasSubscription && <p className="cabinet-caption">Активируйте подписку, чтобы получить персональный ключ подключения</p>}
      </section>
    )
  }

  const selectedPlatform = platforms.find((item) => item.id === platform)
  if (!selectedPlatform) {
    return (
      <section className="setup-screen platform-screen">
        <PagePill title="На другом устройстве" onBack={goBack} />
        <p className="setup-lead">Скачайте приложение на ваше устройство и импортируйте ключ-ссылку</p>
        <div className="platform-list">
          {platforms.map((item) => <button type="button" key={item.id} onClick={() => setPlatform(item.id)}><span>{item.icon}</span><span><strong>{item.title}</strong><small>{item.note}</small></span><ArrowRight /></button>)}
        </div>
      </section>
    )
  }

  return (
    <section className="setup-screen platform-detail-screen">
      <PagePill title={`Настроить на ${selectedPlatform.title}`} onBack={goBack} />
      <ol className="setup-steps">
        <li><span>1</span><div><h2>Скачайте приложение {selectedPlatform.id === 'chrome' ? 'NOVA' : 'Happ'}</h2><p>Установите совместимое приложение из официального магазина или дистрибутива.</p><button type="button" disabled><Download />{selectedPlatform.note.includes('Store') || selectedPlatform.note.includes('Play') ? selectedPlatform.note : `Скачать для ${selectedPlatform.title}`}</button></div></li>
        <li><span>2</span><div><h2>Добавьте ключ-ссылку</h2><p>Скопируйте персональную ссылку VPN и импортируйте её на экране подключения.</p><div className="masked-key"><code>{subscriptionUrl ? maskSubscriptionUrl(subscriptionUrl) : 'Ссылка появится после активации подписки'}</code><button type="button" disabled={!subscriptionUrl} onClick={() => void copySubscriptionUrl()} aria-label="Скопировать ключ-ссылку">{copied ? <Check /> : <Copy />}</button></div>{copied && <small className="copy-success" role="status">Ссылка скопирована</small>}<button className="help-link" type="button" onClick={() => setShowImportHelp(true)}>Как импортировать ссылку?</button></div></li>
      </ol>
      {showImportHelp && <div className="support-modal-backdrop" role="presentation" onMouseDown={() => setShowImportHelp(false)}><article className="support-modal import-modal" role="dialog" aria-modal="true" aria-labelledby="import-title" onMouseDown={(event) => event.stopPropagation()}><button className="support-modal-close" type="button" aria-label="Закрыть" onClick={() => setShowImportHelp(false)}><X /></button><h2 id="import-title">Как импортировать ссылку</h2><div className="import-demo"><span>+</span><i /><i /><i /></div><p>Вставьте ссылку на экране подключения в приложении VPN.</p><button className="reference-primary" type="button" onClick={() => setShowImportHelp(false)}>Понятно</button></article></div>}
    </section>
  )
}

function Devices({ devices, deviceLimit, onRevoke, onNavigate }: {
  devices: Device[]
  deviceLimit: number
  onRevoke: (hardwareId: string) => Promise<void>
  onNavigate: (view: View) => void
}) {
  const [confirming, setConfirming] = useState<string | null>(null)
  const [revoking, setRevoking] = useState<string | null>(null)
  const [deviceError, setDeviceError] = useState<string | null>(null)
  const freeSlots = Math.max(0, deviceLimit - devices.length)

  async function removeDevice(hardwareId: string) {
    if (confirming !== hardwareId) {
      setConfirming(hardwareId)
      return
    }
    setRevoking(hardwareId)
    setDeviceError(null)
    try {
      await onRevoke(hardwareId)
      setConfirming(null)
    } catch (reason) {
      setDeviceError(reason instanceof Error ? reason.message : 'Не удалось удалить устройство')
    } finally {
      setRevoking(null)
    }
  }

  return (
    <section className="devices-screen">
      <PagePill title="Устройства" onBack={() => onNavigate('wallet')} action={<button type="button" aria-label="Добавить устройство" onClick={() => onNavigate('connect')}><Plus /></button>} />
      <article className="connected-devices-card">
        <div><h2>Подключенные устройства</h2><p>Подключено: {devices.length} из {deviceLimit}</p><small>Список обновляется при каждом открытии кабинета.</small></div>
        <div className="device-art" aria-hidden="true"><Smartphone /><TabletSmartphone /></div>
      </article>
      <div className="device-slots">
        {devices.map((device) => (
          <article className="live-device-row" key={device.hardware_id}>
            <span><Smartphone /></span>
            <span><strong>{device.model || device.platform || 'Устройство'}</strong><small>{device.platform || 'Платформа не определена'}{device.last_seen_at ? ` · ${formatDate(device.last_seen_at)}` : ''}</small></span>
            <button className={confirming === device.hardware_id ? 'confirm' : ''} type="button" disabled={revoking === device.hardware_id} onClick={() => void removeDevice(device.hardware_id)}>{revoking === device.hardware_id ? <LoaderCircle className="spinner" /> : confirming === device.hardware_id ? 'Подтвердить' : 'Удалить'}</button>
          </article>
        ))}
        {Array.from({ length: freeSlots }, (_, index) => <button type="button" key={`slot-${index}`} onClick={() => onNavigate('connect')}><span><Plus /></span><span><strong>Добавить устройство</strong><small>Свободное место</small></span></button>)}
        {!devices.length && !freeSlots && <p className="empty-devices">Устройства пока не зарегистрированы или лимит тарифа равен нулю.</p>}
      </div>
      {deviceError && <p className="live-data-error" role="alert">{deviceError}</p>}
    </section>
  )
}

function Referral({ me, onNavigate }: { me: Me; onNavigate: (view: View) => void }) {
  const [linkType, setLinkType] = useState<'site' | 'telegram'>('site')
  const inviteLink = linkType === 'site'
    ? `${window.location.origin}/cabinet?invite=${me.referral_code}`
    : `https://t.me/nova_vpn_bot?start=invite_${me.referral_code}`
  async function copy() {
    await navigator.clipboard.writeText(inviteLink)
    window.Telegram?.WebApp.HapticFeedback?.impactOccurred('medium')
  }
  return (
    <section className="reference-referral">
      <h1 className="reference-page-pill">Реферальная программа</h1>
      <div className="referral-dashboard">
        <div className="referral-stats">
          <article><small>Баланс</small><strong>{formatMoney(me.wallet_balance_minor, me.wallet_currency)}</strong></article>
          <article><small>Всего рефералов</small><strong>0</strong></article>
          <article><small>Всего заработано</small><strong>0 ₽</strong></article>
        </div>
        <article className="withdraw-card">
          <div className="withdraw-ring"><i /></div>
          <small>Нужно накопить</small><strong>1 000 ₽</strong>
          <button type="button" disabled>Вывести</button>
        </article>
      </div>
      <button className="referral-details" type="button" onClick={() => onNavigate('analytics')}>Подробная статистика <ExternalLink /></button>
      <div className="referral-link-section">
        <h2>Ваша ссылка</h2>
        <div className="referral-tabs"><button className={linkType === 'site' ? 'active' : ''} type="button" onClick={() => setLinkType('site')}>Для сайта</button><button className={linkType === 'telegram' ? 'active' : ''} type="button" onClick={() => setLinkType('telegram')}>Для TG</button></div>
        <div className="referral-link-field"><code>{inviteLink}</code><button type="button" onClick={() => void copy()} aria-label="Скопировать ссылку"><Copy /></button></div>
      </div>
    </section>
  )
}

function ReferralAnalytics({ onBack }: { onBack: () => void }) {
  const summary = [
    ['Приглашено', '0'], ['Активные пользователи', '0'], ['Купили подписку', '0'],
    ['Всего заработано', '0 ₽'], ['Выведено', '0 ₽'], ['Доступно', '0 ₽'],
  ]
  return (
    <section className="analytics-screen">
      <PagePill title="Статистика" onBack={onBack} action={<button type="button" aria-label="Обновить"><RotateCw /></button>} />
      <div className="analytics-filter"><button className="active" type="button">Всё время</button><button type="button">30 дней</button><button type="button">7 дней</button></div>
      <div className="analytics-summary">{summary.map(([label, value]) => <article key={label}><small>{label}</small><strong>{value}</strong></article>)}</div>
      <article className="analytics-chart"><header><div><h2>Динамика пользователей</h2><p>Последние 30 дней</p></div><span>0</span></header><div className="chart-grid"><i /><i /><i /><i /><svg viewBox="0 0 300 90" preserveAspectRatio="none" aria-hidden="true"><path d="M0 78 C45 76 61 54 96 62 S155 72 188 45 S244 53 300 20" /></svg></div></article>
      <div className="analytics-bottom-grid"><article><h2>Пользователи</h2><p><span>Всего</span><strong>0</strong></p><p><span>Активные</span><strong>0</strong></p><p><span>Оплатили</span><strong>0</strong></p></article><article><h2>Конверсия</h2><p><span>Пробный → оплата</span><strong>0%</strong></p><p><span>Продлили</span><strong>0%</strong></p><p><span>Перестали платить</span><strong>0%</strong></p></article></div>
    </section>
  )
}

function Profile({ me, access, devices, onNavigate }: { me: Me; access: SubscriptionAccess | null; devices: Device[]; onNavigate: (view: View) => void }) {
  const telegramLabel = me.user.display_name || 'Telegram подключён'
  const [showSoon, setShowSoon] = useState(false)
  return (
    <section className="settings-screen">
      <h1 className="reference-page-pill">Настройки</h1>
      <article className="settings-promo">
        <div><h2>{access?.plan_name ?? 'Подписка'}</h2><p>{access ? `Активна до ${formatDate(access.expires_at)} · ${devices.length} из ${access.device_limit} устройств` : me.subscription ? 'Получаем данные подписки' : 'Подписка не активна'}</p><button type="button" onClick={() => onNavigate('plans')}>Настроить <ArrowRight /></button></div>
        <div className="settings-pro-art" aria-hidden="true"><ShieldCheck /><strong>PRO</strong><i /></div>
      </article>

      <section className="settings-card settings-account">
        <h2>Аккаунт</h2>
        <button type="button" onClick={() => { setShowSoon(true); window.setTimeout(() => setShowSoon(false), 2200) }}><span className="settings-row-icon"><Bell /></span><strong>Уведомления</strong><ArrowRight /></button>
        <button type="button" onClick={() => onNavigate('devices')}><span className="settings-row-icon"><MonitorSmartphone /></span><strong>Устройства</strong><ArrowRight /></button>
      </section>

      <section className="settings-card settings-logins">
        <h2>Способы входа</h2>
        <div className="login-method-row"><span className="login-provider email-provider"><Mail /></span><span><small>Email</small><strong>Email не привязан</strong></span><i><Check /></i></div>
        <div className="login-method-row"><span className="login-provider telegram-provider"><Send /></span><span><small>Telegram</small><strong>{telegramLabel}</strong></span><i><Check /></i></div>
      </section>

      <section className="settings-card settings-information">
        <h2>Информация</h2>
        <button type="button" onClick={() => onNavigate('legal')}><span className="settings-row-icon"><FileText /></span><strong>Пользовательское соглашение</strong><ExternalLink /></button>
        <button type="button" onClick={() => onNavigate('support')}><span className="settings-row-icon"><CircleHelp /></span><strong>Поддержка</strong><ArrowRight /></button>
      </section>
      {showSoon && <div className="cabinet-toast" role="status"><strong>Скоро</strong><span>Раздел в разработке</span></div>}
    </section>
  )
}

function Support({ onNavigate }: { onNavigate: (view: View) => void }) {
  const [activeFaq, setActiveFaq] = useState<number | null>(null)
  const faqs = [
    { title: 'VPN не подключается', text: 'Откройте раздел «Установка», скачайте приложение и импортируйте ключ доступа.' },
    { title: 'Как установить VPN?', text: 'Проверьте подключение к интернету и попробуйте сменить локацию. Если проблема сохраняется — перезапустите приложение.' },
    { title: 'Интернет стал медленнее', text: 'Скорость может зависеть от выбранной локации. Попробуйте подключиться к ближайшему серверу.' },
    { title: 'Нашли баг или ошибку?', text: 'Опишите проблему в чате поддержки — мы постараемся помочь как можно быстрее.' },
  ]
  return (
    <section className="support-screen">
      <h1 className="reference-page-pill">Поддержка</h1>
      <div className="support-faq-list">
        {faqs.map((faq, index) => (
          <button type="button" key={faq.title} onClick={() => setActiveFaq(index)}>
            <span>{index + 1}</span><strong>{faq.title}</strong><ArrowRight />
          </button>
        ))}
      </div>
      <article className="support-chat-card">
        <div><h2>Нужна помощь?</h2><p>Напишите в чат, если возникли<br />проблемы или вопросы</p><button type="button" onClick={() => onNavigate('chat')}>Перейти в чат <ArrowRight /></button></div>
        <span className="support-chat-art" aria-hidden="true"><Headphones /><i /></span>
      </article>
      {activeFaq !== null && (
        <div className="support-modal-backdrop" role="presentation" onMouseDown={() => setActiveFaq(null)}>
          <article className="support-modal" role="dialog" aria-modal="true" aria-labelledby="support-modal-title" onMouseDown={(event) => event.stopPropagation()}>
            <button type="button" className="support-modal-close" onClick={() => setActiveFaq(null)} aria-label="Закрыть"><X /></button>
            <h2 id="support-modal-title">{faqs[activeFaq].title}</h2>
            <p>{faqs[activeFaq].text}</p>
          </article>
        </div>
      )}
    </section>
  )
}

function SupportChat({ onBack }: { onBack: () => void }) {
  const [draft, setDraft] = useState('')
  const [sent, setSent] = useState<string[]>([])
  const topics = ['Как оплатить подписку', 'Рефералка', 'БАГ', 'Подключить новое устройство']

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const message = draft.trim()
    if (!message) return
    setSent((current) => [...current, message])
    setDraft('')
  }

  return (
    <section className="chat-screen">
      <PagePill title="Чат с менеджером" onBack={onBack} />
      <div className="chat-body">
        <div className="chat-greeting"><span><Headphones /></span><div><h2>Здравствуйте 👋</h2><p>С чем вам помочь?</p></div></div>
        <div className="quick-topics">{topics.map((topic) => <button type="button" key={topic} onClick={() => setDraft(topic)}>{topic}</button>)}</div>
        {sent.length > 0 && <div className="chat-messages">{sent.map((message, index) => <div className="chat-message" key={`${message}-${index}`}>{message}</div>)}<div className="chat-system">Сообщение сохранено локально. Подключите провайдера поддержки для отправки.</div></div>}
      </div>
      <form className="chat-composer" onSubmit={submit}>
        <label className="chat-attach" aria-label="Прикрепить файл"><Paperclip /><input type="file" /></label>
        <input value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="Опишите свой вопрос" aria-label="Сообщение" />
        <button type="submit" aria-label="Отправить" disabled={!draft.trim()}><Send /></button>
      </form>
    </section>
  )
}

function LegalDocuments({ onBack }: { onBack: () => void }) {
  return (
    <section className="legal-screen">
      <PagePill title="Документы" onBack={onBack} />
      <article className="legal-document">
        <h1>Политика конфиденциальности</h1>
        <small>Рабочая редакция для первой версии NOVA</small>
        <h2>1. Общие положения</h2>
        <p>NOVA обрабатывает только данные, необходимые для авторизации, управления подпиской, устройствами и обращениями в поддержку.</p>
        <h2>2. Какие данные используются</h2>
        <ul><li>идентификатор и имя профиля Telegram;</li><li>данные подписки, платежного статуса и подключённых устройств;</li><li>сообщения, которые пользователь самостоятельно отправляет в поддержку.</li></ul>
        <h2>3. Технические данные VPN</h2>
        <p>Сервис не должен хранить историю посещённых сайтов или содержимое трафика. Сроки и состав технических журналов необходимо окончательно определить до запуска.</p>
        <h2>4. Защита и удаление</h2>
        <p>Доступ к данным ограничивается сотрудниками, которым он необходим для работы сервиса. Порядок удаления профиля будет опубликован до коммерческого запуска.</p>
      </article>
      <article className="legal-document">
        <h1>Пользовательское соглашение</h1>
        <small>Черновик — требует проверки юристом</small>
        <h2>1. Назначение сервиса</h2><p>NOVA предоставляет доступ к конфигурациям совместимых VPN-приложений при наличии активной подписки.</p>
        <h2>2. Оплата и подписка</h2><p>Цена, срок и количество устройств показываются до оплаты. Автопродление не включается без отдельного согласия пользователя.</p>
        <h2>3. Ограничения</h2><p>Запрещено использовать сервис для спама, атак, распространения вредоносных программ и иных незаконных действий.</p>
        <h2>4. Поддержка</h2><p>Вопросы по подключению, оплате и возвратам принимаются через чат поддержки в личном кабинете.</p>
      </article>
    </section>
  )
}

function PagePill({ title, onBack, action }: { title: string; onBack?: () => void; action?: ReactNode }) {
  return (
    <header className="detail-page-header">
      {onBack ? <button type="button" onClick={onBack} aria-label="Назад"><ArrowLeft /></button> : <span />}
      <h1 className="reference-page-pill">{title}</h1>
      {action ?? <span />}
    </header>
  )
}
