FROM node:22-slim

WORKDIR /app

# Install pnpm
RUN npm install -g pnpm@10.28.1

# Copy monorepo root files
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY packages/ packages/
COPY frontends/wealth/ frontends/wealth/

# Install deps
RUN pnpm install --frozen-lockfile

# Build UI package then wealth frontend
RUN pnpm --filter @netz/ui build && pnpm --filter netz-wealth-os build

WORKDIR /app/frontends/wealth
EXPOSE 3000
CMD ["node", "build/index.js"]
