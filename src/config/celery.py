import os
from celery import Celery

# Définit les réglages par défaut de Django pour celery
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('config')

# Utilise les réglages de settings.py avec le préfixe CELERY_
app.config_from_object('django.conf:settings', namespace='CELERY')

# Découvre automatiquement les tâches dans les apps
app.autodiscover_tasks()

app.conf.timezone = "Africa/Porto-Novo"
app.conf.enable_utc = True


@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
