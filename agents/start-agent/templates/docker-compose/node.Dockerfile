FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
COPY pnpm-lock.yaml* yarn.lock* bun.lock* bun.lockb* ./
RUN if [ -f pnpm-lock.yaml ]; then npm i -g pnpm && pnpm i --frozen-lockfile || pnpm i; \
    elif [ -f yarn.lock ]; then yarn install --frozen-lockfile || yarn install; \
    else npm ci || npm install; fi
COPY . .
ENV NODE_ENV=production
ENV HOST=0.0.0.0
ENV PORT=3000
EXPOSE 3000
CMD ["npm", "start"]
