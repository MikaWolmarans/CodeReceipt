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

CMD uvicorn app.main:app --host 0.0.0.0 --port $PORT
