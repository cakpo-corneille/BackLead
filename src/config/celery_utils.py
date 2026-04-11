# src/config/celery_utils.py
# Module partagé — utilisable par accounts ET core_data sans duplication

import logging
logger = logging.getLogger(__name__)


def has_active_celery_workers(app=None):
    """
    Vérifie si au moins un worker Celery est connecté et actif.
    
    On accepte `app` en paramètre optionnel pour éviter un import circulaire :
    l'appelant passe son app Celery, on n'a pas besoin de l'importer ici.
    Si `app` n'est pas fourni, on l'importe depuis la config principale.
    
    Retourne False en cas de doute — mieux vaut exécuter en synchrone
    que de laisser une tâche orpheline dans la queue.
    """
    try:
        if app is None:
            from config.celery import app as celery_app
            app = celery_app
        
        # inspect() envoie un ping broadcast à tous les workers via Redis.
        # Un timeout court (1s) garantit qu'on ne bloque pas la requête.
        inspector = app.control.inspect(timeout=1.0)
        active_workers = inspector.active()
        
        # active_workers est un dict {worker_name: [tâches_en_cours]}
        # ou None/dict vide si personne ne répond dans le timeout
        return bool(active_workers)
    
    except Exception as exc:
        logger.warning(
            f"[has_active_celery_workers] Vérification impossible : {exc}. "
            f"Fallback synchrone activé."
        )
        return False
