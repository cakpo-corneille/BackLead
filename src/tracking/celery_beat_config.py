# ============================================================
# À ajouter dans ton settings.py
# ============================================================
#
# pip install librouteros cryptography
#
# CELERY_BEAT_SCHEDULE — planification des tâches périodiques

from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {

    # Synchro MikroTik toutes les 2 minutes
    # → met à jour les sessions actives en temps réel
    'sync-mikrotik-routers': {
        'task': 'tracking.sync_all_mikrotik_routers',
        'schedule': 120,  # secondes
    },

    # Filet de sécurité toutes les 10 minutes
    # → ferme les sessions sans signal depuis trop longtemps
    'close-stale-sessions': {
        'task': 'tracking.close_stale_sessions',
        'schedule': 600,  # secondes
    },
}
