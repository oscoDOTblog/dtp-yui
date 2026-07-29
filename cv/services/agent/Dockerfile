FROM mcr.microsoft.com/playwright:v1.54.2-jammy

WORKDIR /app

COPY package.json ./
RUN npm install --omit=dev

COPY src ./src
COPY config.example.json ./config.example.json

ENV NODE_ENV=production
ENV CV_AGENT_PORT=8010
ENV CV_AGENT_HEADLESS=1
ENV CV_API_BASE=http://api:8000
ENV CV_AGENT_PROFILE_DIR=/app/browser-profile
ENV CV_AGENT_SCREENSHOT_DIR=/app/screenshots
ENV CV_AGENT_CONFIG=/app/config/agent.json

EXPOSE 8010

CMD ["node", "src/index.js"]
