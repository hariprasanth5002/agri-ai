# ───────────────────────────────────────────
# Agri AI Backend — Production Dockerfile
# ───────────────────────────────────────────

# Stage 1: Build the React/Vite Frontend
FROM node:20-alpine AS build-frontend
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# Stage 2: Build the FastAPI Backend
FROM python:3.11-slim

# Prevent Python from writing .pyc and enable unbuffered logs
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (Docker layer cache)
COPY requirements.txt .

# Install Python dependencies with CPU-only PyTorch
RUN pip install --no-cache-dir \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    -r requirements.txt

# Copy backend source code
COPY intelligence_service.py .
COPY run_api.py .
COPY pipeline/ ./pipeline/
COPY services/ ./services/
COPY models/__init__.py models/embedding_model.py ./models/
COPY rag/ ./rag/
COPY nlp/ ./nlp/
COPY utils/ ./utils/
COPY knowledge_base/ ./knowledge_base/

# Copy compiled frontend from Stage 1 into the backend's expected directory
COPY --from=build-frontend /app/frontend/dist /app/frontend

# Expose port (Render sets PORT env var)
EXPOSE 10000

# Start the server — Render injects $PORT
CMD ["sh", "-c", "uvicorn intelligence_service:app --host 0.0.0.0 --port ${PORT:-10000}"]
