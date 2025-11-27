# Multi-stage build for Bitcoin DCA Service
# Stage 1: Builder
FROM python:3.12-slim AS builder

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install poetry
RUN pip install --no-cache-dir poetry==2.1.2

# Set working directory
WORKDIR /app

# Copy poetry files (README.md is needed for poetry)
COPY pyproject.toml poetry.lock* README.md ./

# Copy source code
COPY src ./src
COPY dca_service/src ./dca_service/src

# Configure poetry to create venv in project directory
RUN poetry config virtualenvs.in-project true

# Install dependencies
RUN poetry install --only main --no-interaction --no-ansi

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

# Copy venv from builder stage
COPY --from=builder /app/.venv /app/.venv

# Add venv bin to PATH
ENV PATH="/app/.venv/bin:$PATH"

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
