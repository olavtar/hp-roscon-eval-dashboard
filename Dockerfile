# Plain multi-arch Python base (amd64 + aarch64) -- the demo machine is aarch64.
FROM docker.io/library/python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src
COPY config/ ./config

ENV PYTHONPATH=/app/src
ENV PORT=8080
EXPOSE 8080

CMD ["python", "-m", "eval_dashboard.main"]
