FROM public.ecr.aws/docker/library/node:22.18-alpine AS build
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
ARG VITE_API_URL=http://localhost:8080
ARG VITE_TELEGRAM_BOT_URL=/cabinet?app=1
ENV VITE_API_URL=$VITE_API_URL
ENV VITE_TELEGRAM_BOT_URL=$VITE_TELEGRAM_BOT_URL
RUN pnpm build

FROM public.ecr.aws/docker/library/nginx:1.29-alpine
COPY nginx-main.conf /etc/nginx/nginx.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --chown=nginx:nginx --from=build /app/dist /usr/share/nginx/html
USER nginx
EXPOSE 8080
