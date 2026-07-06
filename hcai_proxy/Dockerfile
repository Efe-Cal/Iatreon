FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY hcai_proxy ./hcai_proxy

EXPOSE 8787

CMD ["uvicorn", "hcai_proxy.main:app", "--host", "0.0.0.0", "--port", "8787", "--no-access-log"]
