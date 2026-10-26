FROM node:22.12.0-bookworm-slim

WORKDIR /frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./

ENV VITE_API_URL=http://127.0.0.1:8000
EXPOSE 5173

CMD ["./node_modules/.bin/vite", "--host", "0.0.0.0", "--port", "5173", "--strictPort"]
