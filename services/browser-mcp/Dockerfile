FROM node:22-bookworm-slim

WORKDIR /app
RUN corepack enable && corepack prepare pnpm@10.24.0 --activate

COPY package.json ./
RUN pnpm install --prod --frozen-lockfile=false

COPY server.mjs ./

USER node
ENTRYPOINT ["node", "/app/server.mjs"]
