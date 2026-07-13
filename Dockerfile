# Multi-stage production-grade Dockerfile for Scan Chain Diagnosis Agent
# ---------------------------------------------------------------------
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install dependencies into a wheels directory
RUN pip install --no-cache-dir --user -r requirements.txt

# ---------------------------------------------------------------------
FROM python:3.11-slim AS runner

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /root/.local /root/.local
COPY . .

ENV PATH=/root/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1

EXPOSE 8502

# Run Streamlit dashboard by default
ENTRYPOINT ["streamlit", "run", "src/app.py", "--server.port", "8502", "--server.address", "0.0.0.0"]
