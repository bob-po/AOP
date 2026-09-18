# syntax=docker/dockerfile:1
FROM node:20-alpine AS deps
WORKDIR /app
ARG NPM_REGISTRY=https://registry.npmmirror.com
COPY package.json package-lock.json* ./
RUN npm config set registry "${NPM_REGISTRY}" \
  && npm ci

FROM node:20-alpine AS build
WORKDIR /app
ARG NPM_REGISTRY=https://registry.npmmirror.com
ARG NEXT_PUBLIC_API_BASE=http://127.0.0.1:8080
ARG NEXT_PUBLIC_API_KEY=
ENV NEXT_PUBLIC_API_BASE=${NEXT_PUBLIC_API_BASE}
ENV NEXT_PUBLIC_API_KEY=${NEXT_PUBLIC_API_KEY}
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm config set registry "${NPM_REGISTRY}" \
  && npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000
COPY --from=build /app/package.json ./
COPY --from=build /app/.next ./.next
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/next.config.js ./
RUN mkdir -p ./public
COPY --from=build /app/public ./public
EXPOSE 3000
CMD ["npm", "run", "start"]
