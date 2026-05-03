import os
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = "Crée un superutilisateur non interactif à partir des variables d'environnement"

    def handle(self, *args, **options):
        User = get_user_model()
        email = os.getenv('DJANGO_SUPERUSER_EMAIL','')
        password = os.getenv('DJANGO_SUPERUSER_PASSWORD','')

        if not User.objects.filter(email=email).exists():
            User.objects.create_superuser(email=email, password=password)
            self.stdout.write(self.style.SUCCESS(f"✅ Superutilisateur '{email}' créé avec succès."))
        else:
            self.stdout.write(self.style.WARNING(f"⚠️ Le superutilisateur '{email}' existe déjà."))
