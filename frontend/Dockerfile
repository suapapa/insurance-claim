# syntax=docker/dockerfile:1
#
# 프론트엔드(정적 UI) 이미지. 빌드 컨텍스트는 frontend/ 디렉터리:
#   docker build -f frontend/Dockerfile frontend
#   (또는 docker-compose.yml의 frontend 서비스)
#
# UI는 상대 경로(/api/...)로 백엔드를 호출하므로, nginx가 /api를 백엔드로
# 프록시한다. 백엔드 서비스 이름을 바꾸려면 이 ARG도 함께 맞춰야 한다.

FROM nginx:1.27-alpine AS runtime

# docker-compose.yml의 backend 서비스명·포트
ARG BACKEND_HOST=backend:8321

COPY nginx.conf /tmp/nginx.conf.template
# 빌드 시점에 ARG를 설정된 값으로 치환 (nginx 안의 $uri 등은 건드리지 않는다)
RUN envsubst '${BACKEND_HOST}' < /tmp/nginx.conf.template \
        > /etc/nginx/conf.d/default.conf \
    && rm /tmp/nginx.conf.template

COPY index.html app.js style.css /usr/share/nginx/html/

EXPOSE 80

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -q --spider http://127.0.0.1/healthz || exit 1
