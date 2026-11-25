# Branche STABLE de nginx (correctifs de sécurité, sans les nouveautés de
# la branche principale) ; reconstruire régulièrement pour les recevoir.
FROM nginx:stable-alpine

# Copy the custom NGINX configuration
COPY nginx.conf /etc/nginx/nginx.conf
COPY 15-real-ip.sh /docker-entrypoint.d/15-real-ip.sh
RUN chmod +x /docker-entrypoint.d/15-real-ip.sh && touch /etc/nginx/real-ip.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
