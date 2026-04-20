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
COPY frontends/terminal/ frontends/terminal/

# Install deps
RUN pnpm install --frozen-lockfile

# Build-time env vars (Railway injects these as build args automatically)
ARG PUBLIC_CLERK_PUBLISHABLE_KEY
ARG PUBLIC_API_BASE_URL
ENV PUBLIC_CLERK_PUBLISHABLE_KEY=$PUBLIC_CLERK_PUBLISHABLE_KEY
ENV PUBLIC_API_BASE_URL=$PUBLIC_API_BASE_URL

# Build UI packages then terminal frontend
RUN pnpm --filter @netz/ui build \
  && pnpm --filter @investintell/ui build \
  && pnpm --filter @investintell/ii-terminal-core build \
  && pnpm --filter ii-terminal build

WORKDIR /app/frontends/terminal
EXPOSE 3000
CMD ["node", "build/index.js"]
