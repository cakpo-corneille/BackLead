from django.apps import AppConfig


class SuperadminConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'superadmin'
    verbose_name = 'Dashboard Superadmin'

    def ready(self):
        pass
