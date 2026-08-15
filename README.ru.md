# Rovyn VPN Platform — руководство на русском

Rovyn — VPN-сервис с Telegram-ботом и Mini App. Пользователь открывает
личный кабинет, выбирает тариф, оплачивает его через СБП в YooKassa и получает
персональную подписку Remnawave для Happ или v2RayTun.

## Состав проекта

- `backend/` — FastAPI: авторизация Telegram, тарифы, платежи, подписки,
  устройства и интеграция с Remnawave.
- `bot/` — Telegram-бот на aiogram с кнопками «Личный кабинет» и «Открыть
  VPN».
- `miniapp/` — публичный сайт и адаптивный Telegram Mini App.
- `infra/` — Docker Compose, Caddy и скрипты инфраструктуры.
- `mockups/` — исходный визуальный макет кабинета.

## Локальный запуск

Требуются Docker Compose v2, Python 3.12+, Node.js 22+ и pnpm.

```bash
git clone https://github.com/Yan-L0/rovyn-vpn-platform.git
cd rovyn-vpn-platform
cp .env.example .env
docker compose --env-file .env -f infra/compose.local.yml up --build
```

Адреса после запуска:

- сайт: `http://localhost:5173`;
- Mini App: `http://localhost:5173/cabinet?app=1`;
- Swagger API: `http://localhost:8080/docs`.

Для локального просмотра интерфейса без Telegram разрешён только локальный
режим `TELEGRAM_AUTH_DEV_BYPASS=true`. В production он должен быть выключен.

Остановка:

```bash
docker compose --env-file .env -f infra/compose.local.yml down
```

## Настройка production

1. Скопируйте `.env.production.example` в приватный `.env.production`.
2. Заполните Telegram-токен, `SESSION_SECRET`, токен Remnawave и ключи
   YooKassa. Этот файл нельзя добавлять в Git.
3. Замените домены `bot.vpn.example`, `panel.vpn.example`,
   `node.vpn.example` и `subscription.vpn.example` на свои домены только в
   приватной production-конфигурации.
4. Настройте TLS через `infra/Caddyfile`.
5. Запустите приложение и бота:

```bash
docker compose --env-file .env.production \
  -f infra/compose.prod.yml --profile telegram up -d --build
```

Проверка:

```bash
curl --fail https://ВАШ_ДОМЕН/health/ready
docker compose --env-file .env.production -f infra/compose.prod.yml ps
```

Readiness должен показать исправные `postgres`, `redis` и `vpn_provider`.

## Remnawave и нода

Панель и нода размещаются отдельно от приложения. Создайте ноду в Remnawave,
настройте сертификаты и запустите `infra/compose.node.yml`. Перед выдачей
пользователям проверьте профили VLESS Reality и Hysteria2 скриптами из
`infra/`.

Порт управления нодой не должен быть открыт для всего Интернета.

## YooKassa и Telegram

В BotFather укажите URL Mini App. В YooKassa добавьте webhook:

```text
https://ВАШ_ДОМЕН/api/v1/payments/yookassa/webhook
```

Перед запуском продаж выполните тестовый платёж через СБП и убедитесь, что
после подтверждения платежа создаётся подписка Remnawave.

## Проверка качества

```bash
make test
make lint
npm --prefix miniapp run build
```

Публичный репозиторий не должен содержать реальные токены, приватные ключи,
дампы баз данных, VPS-адреса или production-файлы окружения.
