from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = 'accounts'

    def ready(self):
        # Import signals to ensure they are registered
        from . import signals  # noqa: F401
