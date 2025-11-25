# Multi-stage build for Bitcoin DCA Service
# Stage 1: Builder
FROM python:3.12-slim as builder

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install poetry
RUN pip install --no-cache-dir poetry==1.7.1

# Set working directory
WORKDIR /app

# Copy poetry files
COPY pyproject.toml poetry.lock* ./

# Configure poetry to not create virtual env (we're in a container)
RUN poetry config virtualenvs.create false

# Install dependencies
RUN poetry install --no-dev --no-interaction --no-ansi

# Stage 2: Runtime
FROM python:3.12-slim

# Install runtime dependencies only
RUN apt-get update && apt-get install -y \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 dcauser

# Set working directory
WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY --chown=dcauser:dcauser . .

# Create necessary directories
RUN mkdir -p /app/data && chown -R dcauser:dcauser /app

# Switch to non-root user
USER dcauser

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "dca_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
