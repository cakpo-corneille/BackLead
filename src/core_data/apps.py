from django.apps import AppConfig


class CoreDataConfig(AppConfig):
    name = 'core_data'

    def ready(self):
        # import signals to ensure FormSchema default creation
        try:
            from . import signals  # noqa
        except Exception:
            pass
