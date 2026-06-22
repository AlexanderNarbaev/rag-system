FROM python:3.14-slim

WORKDIR /app

COPY federation/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY federation/app/ ./app/

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
