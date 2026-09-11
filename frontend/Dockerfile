FROM node:22-alpine AS builder
WORKDIR /app
COPY package*.json ./
# `npm ci` et non `npm install` : installe EXACTEMENT les versions du
# package-lock.json, et échoue s'il n'est plus à jour. `install` peut tirer
# une version plus récente, jamais auditée, à chaque construction.
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
