FROM node:22-slim

WORKDIR /app

# Install pnpm
RUN npm install -g pnpm@10.28.1

# Cache bust to force fresh copy on every build
ARG RAILWAY_GIT_COMMIT_SHA
RUN echo "build: ${RAILWAY_GIT_COMMIT_SHA:-unknown}"

# Copy monorepo root files
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY packages/ packages/
COPY frontends/wealth/ frontends/wealth/

# Install deps
RUN pnpm install --frozen-lockfile

# Build-time env vars (Railway injects these as build args automatically)
ARG PUBLIC_CLERK_PUBLISHABLE_KEY
ARG VITE_API_BASE_URL
ENV PUBLIC_CLERK_PUBLISHABLE_KEY=$PUBLIC_CLERK_PUBLISHABLE_KEY
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

# Build UI package then wealth frontend
RUN pnpm --filter @netz/ui build && pnpm --filter netz-wealth-os build

WORKDIR /app/frontends/wealth
EXPOSE 3000
CMD ["node", "build/index.js"]
