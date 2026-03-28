web: gunicorn "app:create_app()" --bind 0.0.0.0:$PORT --workers 3 --worker-class gthread --threads 4 --timeout 30 --max-requests 1000 --max-requests-jitter 50 --access-logfile -
release: bash release.sh
