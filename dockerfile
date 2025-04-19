FROM python:3.10
WORKDIR /app
RUN apt-get update && apt-get install -y \
    && rm -rf /var/lib/apt/lists/*
COPY . .
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt
EXPOSE 8000
CMD ["python", "main.py"]
