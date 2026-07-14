FROM python:3.12-slim

WORKDIR /app
COPY backend_api/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend_api ./backend_api

CMD ["uvicorn", "backend_api.main:app", "--host", "0.0.0.0", "--port", "8787", "--no-access-log"]
