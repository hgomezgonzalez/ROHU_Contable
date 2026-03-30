FROM python:3.11-slim

# Install system dependencies (Tesseract OCR + Spanish language)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-spa libtesseract-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Set default environment variables
ENV FLASK_APP=app:create_app \
    FLASK_ENV=production \
    PORT=5000 \
    TESSDATA_PREFIX=/usr/share/tesseract-ocr/4/tessdata/

EXPOSE $PORT

# Entrypoint: run migrations, seed, then start gunicorn
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

ENTRYPOINT ["/docker-entrypoint.sh"]
