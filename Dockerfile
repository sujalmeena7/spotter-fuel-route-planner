# Spotter Fleet Fuel Route Planner
# High-performance Python 3.12 container with pre-warmed spatial indexes

FROM python:3.12-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

# Install system dependencies (curl for healthchecks)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source and assets
COPY . /app

# Ensure static assets are collected and db directory permissions exist
RUN python manage.py collectstatic --noinput

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

# Run migrations, load stations (idempotent), and start gunicorn with 3 workers
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py load_stations && exec gunicorn config.wsgi:application --config gunicorn.conf.py"]
