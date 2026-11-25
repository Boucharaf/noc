# Node 24 : version LTS active (support de sécurité jusqu'en 2028).
FROM node:24-alpine AS builder
WORKDIR /app
COPY package*.json ./
# `npm ci` et non `npm install` : installe EXACTEMENT les versions du
# package-lock.json, et échoue s'il n'est plus à jour. `install` peut tirer
# une version plus récente, jamais auditée, à chaque construction.
RUN npm ci
COPY . .
RUN npm run build

# Branche STABLE de nginx (correctifs de sécurité, sans les nouveautés de
# la branche principale) ; reconstruire régulièrement pour les recevoir.
FROM nginx:stable-alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
