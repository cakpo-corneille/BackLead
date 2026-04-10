web: gunicorn config.wsgi:application --chdir src --log-file -
worker: celery -A config worker -l info --chdir src
