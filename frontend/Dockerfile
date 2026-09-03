FROM node:24.15.0-alpine AS dependencies

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts

FROM dependencies AS verification

COPY frontend/ ./
COPY tests/frontend/ ./tests/frontend/
# 有三条测试要读 deploy/nginx/ 下的线上配置模板（校验 SSE 的 X-Real-IP、
# VPN 与 W-S 机器端点的 location 精确匹配）。以前构建里 npm test 跑 0 条，
# 缺这个目录也没人发现；闸门修好后它们会因 ENOENT 直接挡住构建。
COPY deploy/nginx/ ./deploy/nginx/
RUN ln -s . frontend \
    && npm run test:ci \
    && rm frontend
RUN npm run verify
RUN npm run typecheck

FROM verification AS build

ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:24.15.0-alpine AS runtime

ENV HOSTNAME=0.0.0.0
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000

RUN addgroup -S nodejs -g 1001 \
    && adduser -S nextjs -u 1001 -G nodejs

WORKDIR /app
COPY --from=build --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=build --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=build --chown=nextjs:nodejs /app/public ./public

USER nextjs
EXPOSE 3000

CMD ["node", "server.js"]
