web: cd src && gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 1 --timeout 120 --log-file -
worker: cd src && celery -A config worker --loglevel=info --concurrency=2
