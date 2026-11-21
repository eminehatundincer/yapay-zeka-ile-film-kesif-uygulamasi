# ==============================================================================
# Stage 1: React + Vite Üretim Derleme Aşaması (node:20-alpine)
# ==============================================================================
FROM node:20-alpine AS builder

WORKDIR /app

# Bağımlılıkları kur
COPY package.json package-lock.json ./
RUN npm ci

# Vite derleme zamanı ortam değişkenlerini ARG olarak al ve ENV olarak aktar
ARG VITE_BACKEND_HOST=localhost
ARG VITE_BACKEND_PORT=8005
ARG VITE_SECURE=false

ENV VITE_BACKEND_HOST=$VITE_BACKEND_HOST \
    VITE_BACKEND_PORT=$VITE_BACKEND_PORT \
    VITE_SECURE=$VITE_SECURE

# Kaynak kodları kopyala ve üretim derlemesini oluştur
COPY . .
RUN npm run build

# ==============================================================================
# Stage 2: Nginx Statik Sunum Aşaması (nginx:alpine)
# ==============================================================================
FROM nginx:alpine

# Özel Nginx yapılandırmasını kopyala
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Derlenen üretim dosyalarını Nginx statik dizinine kopyala
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
