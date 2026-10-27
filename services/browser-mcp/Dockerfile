FROM mcr.microsoft.com/playwright:v1.64.1-noble

WORKDIR /app

COPY package.json ./
RUN npm install --omit=dev --ignore-scripts=false

COPY server.mjs create-session.mjs network-policy.mjs ./

USER pwuser
ENV HOME=/home/pwuser
ENTRYPOINT ["node", "/app/server.mjs"]
