FROM python:3.13-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY app ./app
COPY pyproject.toml .

RUN pip install --no-cache-dir -e .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
