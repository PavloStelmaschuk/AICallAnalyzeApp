FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml ./
COPY src ./src
COPY config.yaml ./config.yaml

RUN pip install --no-cache-dir .

CMD ["python", "-m", "src.main"]

