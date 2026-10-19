# Optional container image: builds the Angular app and serves it with nginx.
FROM node:22-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci --legacy-peer-deps
COPY . .
RUN npx ng build

FROM nginx:1.27-alpine
COPY --from=build /src/dist/frontend/browser /usr/share/nginx/html
# Single-page app routing: unknown paths fall back to index.html.
RUN printf 'server {\n  listen 80;\n  root /usr/share/nginx/html;\n  location / { try_files $uri $uri/ /index.html; }\n}\n' > /etc/nginx/conf.d/default.conf
EXPOSE 80
