# UNTESTED in the authoring sandbox (no Docker there). Same code paths as `python3 -m ...`; review before a real deployment.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN useradd -m -u 10001 app
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /app/data && chown -R app:app /app/data
USER app
EXPOSE 8000 8001
CMD ["python3", "-m", "saas.main", "--host", "0.0.0.0"]
