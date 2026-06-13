FROM mcr.microsoft.com/playwright/python:v1.51.0-noble

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Chromium + all system deps are already present in the base image.
# Re-register so playwright's path lookup works correctly inside the container.
RUN playwright install chromium

# Copy application code
COPY . .

# Shell form via `sh -c` so ${PORT} is expanded at runtime, with a sane
# default when the platform doesn't inject one.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
