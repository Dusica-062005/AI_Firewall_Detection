# Optional container image for the firewall backend and the mock CloudLink receiver.
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m spacy download en_core_web_md

COPY app ./app

RUN useradd --create-home firewall && mkdir -p /app/data && chown firewall /app/data
USER firewall

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
