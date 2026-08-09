# Multi-stage build so the runtime image only ever contains next build's
# standalone output, not the full node_modules tree or dev dependencies.

FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# NEXT_PUBLIC_* vars are inlined into the client JS bundle at build time —
# there is no runtime env var that can change this after the image is
# built, so it has to be a build ARG, not a Helm-injected container env var.
ARG NEXT_PUBLIC_API_URL=http://app.local/api
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
# Next's standalone output already includes a minimal node_modules and a
# server.js entrypoint — no npm install needed in this stage at all.
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

RUN addgroup -S app && adduser -S app -G app
USER app

EXPOSE 3000
CMD ["node", "server.js"]
