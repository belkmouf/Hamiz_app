FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Africa/Algiers
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY pulse ./pulse
COPY web ./web
RUN useradd -m pulse && chown -R pulse /app
USER pulse
EXPOSE 8000
# Web: uvicorn. Cron: override the command with `python -m pulse.sync`.
CMD ["sh", "-c", "uvicorn pulse.api:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
