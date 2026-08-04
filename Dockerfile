# Base: Playwright Python image (Chromium + system deps preinstalled).
# Pinned to the local playwright version (1.62.0) so the bundled browser matches.
FROM mcr.microsoft.com/playwright/python:v1.62.0

# CJK + general fonts so the dashboard's Chinese renders correctly in headless Chromium.
RUN apt-get update \
 && apt-get install -y --no-install-recommends fonts-noto-cjk fonts-noto \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data /app/static

ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# Bind 0.0.0.0 so the host nginx can reach it via the mapped port.
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
