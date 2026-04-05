FROM ultralytics/ultralytics:latest-cpu

WORKDIR /app

COPY requirements-slim.txt .
RUN pip install --no-cache-dir -r requirements-slim.txt

COPY . .
RUN mkdir -p weights

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]