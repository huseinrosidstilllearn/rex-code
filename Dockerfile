# Rex Code — Docker image for Linux / macOS hosts.
# Runs the FastAPI dashboard (and the GitHub webhook receiver) in a container.
#
# Build & run:
#   docker compose up --build
# or manually:
#   docker build -t rex-code .
#   docker run -p 8000:8000 --env-file .env -v "$PWD/workspace:/app/workspace" \
#     -v "$PWD/sessions:/app/sessions" -v "$PWD/logs:/app/logs" rex-code

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Copy dependency manifest first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application.
COPY . .

# Non-root user for defense in depth.
RUN useradd --create-home --uid 1000 rex && \
    mkdir -p /app/workspace /app/sessions /app/logs /app/workflows && \
    chown -R rex:rex /app
USER rex

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/config')" || exit 1

CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]