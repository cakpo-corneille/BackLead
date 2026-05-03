"""
Management command pour peupler l'app core_data avec des données de test réalistes.

Usage:
    python manage.py populate_core_data
    python manage.py populate_core_data --leads 200
    python manage.py populate_core_data --clear --leads 500

Options:
    --clear       : Supprimer les leads et réinitialiser les schémas existants
    --leads <n>   : Nombre total de leads à créer (défaut : 100)
"""
import random
import uuid
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db import IntegrityError, models
from core_data.models import FormSchema, OwnerClient
from core_data.services.portal.verification_services import _extract_names_from_payload
from faker import Faker

User = get_user_model()


# ---------------------------------------------------------------------------
# Données de référence
# ---------------------------------------------------------------------------

VILLES_BENIN = [
    'Cotonou', 'Porto-Novo', 'Parakou', 'Abomey-Calavi', 'Djougou',
    'Bohicon', 'Natitingou', 'Ouidah', 'Lokossa', 'Abomey', 'Savalou',
    'Nikki', 'Kandi', 'Malanville', 'Sakété'
]

SOURCES = [
    'Facebook', 'Instagram', 'Google', 'Bouche-à-oreille',
    'Affiche', 'Recommandation', 'LinkedIn'
]

INTERETS = ['Produits', 'Services', 'Événements', 'Partenariat', 'Information', 'Autre']

PREFERENCES_CULINAIRES = ['Africain', 'Européen', 'Asiatique', 'Végétarien', 'Fast-food']

SAMPLE_TAGS = [
    ['VIP'], ['Nouveau'], ['Fidèle'], ['Prospect'],
    ['VIP', 'Fidèle'], ['Nouveau', 'Prospect'], ['Fidèle'],
    [], [], []  # La plupart des clients n'ont pas de tags
]

SAMPLE_NOTES = [
    'Client très apprécié, à contacter en priorité.',
    'Préfère être contacté par WhatsApp.',
    'A demandé une offre spéciale pour son anniversaire.',
    'Cliente régulière du vendredi soir.',
    None, None, None, None, None, None  # La majorité sans notes
]

# ---------------------------------------------------------------------------
# Schémas de formulaires variés par type d'établissement
# ---------------------------------------------------------------------------

SCHEMAS = [
    {
        'name': 'Formulaire Simple',
        'title': 'Bienvenue !',
        'description': 'Remplissez ce formulaire pour accéder au WiFi.',
        'button_label': 'Accéder au WiFi',
        'schema': {
            'fields': [
                {'name': 'nom', 'label': 'Nom complet', 'type': 'text', 'required': True},
                {'name': 'email', 'label': 'Email', 'type': 'email', 'required': True},
                {'name': 'phone', 'label': 'Téléphone', 'type': 'phone', 'required': False},
            ]
        }
    },
    {
        'name': 'Formulaire Complet',
        'title': 'Accès WiFi Gratuit',
        'description': 'Quelques informations pour vous connecter et bénéficier de nos offres.',
        'button_label': 'Me connecter',
        'schema': {
            'fields': [
                {'name': 'nom', 'label': 'Nom', 'type': 'text', 'required': True},
                {'name': 'prenom', 'label': 'Prénom', 'type': 'text', 'required': True},
                {'name': 'email', 'label': 'Email', 'type': 'email', 'required': True},
                {'name': 'phone', 'label': 'Téléphone', 'type': 'phone', 'required': True},
                {
                    'name': 'source', 'label': 'Comment nous avez-vous connu ?',
                    'type': 'choice',
                    'choices': ['Facebook', 'Instagram', 'Google', 'Bouche-à-oreille', 'Autre'],
                    'required': False
                },
            ]
        }
    },
    {
        'name': 'Formulaire Marketing',
        'title': 'Connectez-vous gratuitement',
        'description': 'Rejoignez notre communauté et accédez à des offres exclusives.',
        'button_label': 'Rejoindre et se connecter',
        'schema': {
            'fields': [
                {'name': 'nom_complet', 'label': 'Nom complet', 'type': 'text', 'required': True},
                {'name': 'email', 'label': 'Adresse email', 'type': 'email', 'required': True},
                {'name': 'phone', 'label': 'WhatsApp', 'type': 'phone', 'required': False},
                {'name': 'ville', 'label': 'Ville', 'type': 'text', 'required': False},
                {
                    'name': 'interet', 'label': 'Intérêt principal',
                    'type': 'choice',
                    'choices': ['Produits', 'Services', 'Événements', 'Partenariat'],
                    'required': False
                },
            ]
        }
    },
    {
        'name': 'Formulaire Restaurant',
        'title': 'Bienvenue au restaurant !',
        'description': 'Profitez du WiFi et restez informé de nos menus du jour.',
        'button_label': 'Accéder et me connecter',
        'schema': {
            'fields': [
                {'name': 'nom', 'label': 'Nom', 'type': 'text', 'required': True},
                {'name': 'email', 'label': 'Email', 'type': 'email', 'required': True},
                {'name': 'phone', 'label': 'Téléphone', 'type': 'phone', 'required': True},
                {
                    'name': 'preference', 'label': 'Préférence culinaire',
                    'type': 'choice',
                    'choices': ['Africain', 'Européen', 'Asiatique', 'Végétarien'],
                    'required': False
                },
            ]
        }
    },
    {
        'name': 'Formulaire Hôtel',
        'title': 'Connexion WiFi Hôtel',
        'description': 'Merci de compléter votre profil pour accéder au WiFi haut débit.',
        'button_label': 'Confirmer et se connecter',
        'schema': {
            'fields': [
                {'name': 'nom', 'label': 'Nom', 'type': 'text', 'required': True},
                {'name': 'email', 'label': 'Email', 'type': 'email', 'required': True},
                {'name': 'phone', 'label': 'Téléphone', 'type': 'phone', 'required': False},
            ]
        }
    },
]


class Command(BaseCommand):
    help = 'Peuple la base de données avec des schémas de formulaires et des leads de test'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Supprimer tous les leads existants avant de peupler',
        )
        parser.add_argument(
            '--leads',
            type=int,
            default=100,
            help='Nombre total de leads à créer (défaut : 100)',
        )

    def handle(self, *args, **options):
        fake = Faker(['fr_FR'])

        if options['clear']:
            self.stdout.write(self.style.WARNING('Suppression des leads existants...'))
            OwnerClient.objects.all().delete()
            self.stdout.write(self.style.SUCCESS('✓ Leads supprimés'))

        total_leads_to_create = options['leads']

        # Récupérer tous les utilisateurs non-superuser
        owners = list(User.objects.filter(is_superuser=False))

        if not owners:
            self.stdout.write(
                self.style.ERROR(
                    "✗ Aucun propriétaire trouvé. Lancez d'abord : python manage.py populate_accounts"
                )
            )
            return

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f'Création de {total_leads_to_create} leads pour {len(owners)} propriétaires...'
            )
        )

        total_schemas = 0
        total_leads = 0
        leads_by_owner = {owner.id: 0 for owner in owners}

        # Assigner un schéma à chaque owner
        self.stdout.write(self.style.MIGRATE_HEADING('\nAssignation des schémas...'))
        for owner in owners:
            schema_data = random.choice(SCHEMAS)
            schema, created = FormSchema.objects.update_or_create(
                owner=owner,
                defaults={
                    'name': schema_data['name'],
                    'schema': schema_data['schema'],
                    'title': schema_data['title'],
                    'description': schema_data['description'],
                    'button_label': schema_data['button_label'],
                    'opt': random.choice([True, False, False]),  # 1/3 de chance d'activer
                    'enable': True,
                }
            )

            if created:
                total_schemas += 1

            action = 'créé' if created else 'mis à jour'
            self.stdout.write(
                self.style.SUCCESS(
                    f'  ✓ Schéma "{schema_data["name"]}" {action} pour {owner.email}'
                )
            )

        # Distribution pondérée (Pareto 80/20) pour simuler une base réaliste
        self.stdout.write(self.style.MIGRATE_HEADING('\nCréation des leads...'))
        weights = [random.paretovariate(1.5) for _ in owners]
        total_weight = sum(weights)
        normalized_weights = [w / total_weight for w in weights]

        for i in range(total_leads_to_create):
            owner = random.choices(owners, weights=normalized_weights)[0]
            schema = FormSchema.objects.get(owner=owner)

            # Générer des données réalistes avec Faker
            first_name = fake.first_name()
            last_name = fake.last_name()
            full_name = f'{first_name} {last_name}'

            email_domain = random.choice(['gmail.com', 'yahoo.fr', 'hotmail.com', 'outlook.com'])
            email = f'{fake.user_name()}{random.randint(1, 999)}@{email_domain}'

            phone_prefix = random.choice(['97', '96', '95', '94', '93', '92', '91', '90'])
            phone = f'+229{phone_prefix}{random.randint(100000, 999999)}'

            mac = ':'.join([f'{random.randint(0, 255):02X}' for _ in range(6)])

            # Construire le payload selon le schéma
            fields = schema.schema['fields']
            payload = {}

            for field in fields:
                field_name = field['name']
                field_type = field['type']

                if field_name == 'nom':
                    payload['nom'] = last_name
                elif field_name == 'prenom':
                    payload['prenom'] = first_name
                elif field_name == 'nom_complet':
                    payload['nom_complet'] = full_name
                elif field_name == 'email':
                    payload['email'] = email if random.random() > 0.05 else ''
                elif field_name in ['phone', 'whatsapp']:
                    payload[field_name] = phone if random.random() > 0.15 else ''
                elif field_name == 'source':
                    payload['source'] = random.choice(SOURCES)
                elif field_name == 'ville':
                    payload['ville'] = random.choice(VILLES_BENIN)
                elif field_name == 'interet':
                    payload['interet'] = random.choice(INTERETS)
                elif field_name == 'preference':
                    payload['preference'] = random.choice(PREFERENCES_CULINAIRES)
                elif field_type == 'choice':
                    choices = field.get('choices', [])
                    if choices:
                        payload[field_name] = random.choice(choices)
                elif field_type == 'text':
                    payload[field_name] = fake.word().capitalize()

            # Date de création aléatoire (dans les 90 derniers jours)
            days_ago = random.randint(0, 90)
            hours_offset = random.randint(0, 23)
            minutes_offset = random.randint(0, 59)

            created_at = timezone.now() - timedelta(
                days=days_ago,
                hours=hours_offset,
                minutes=minutes_offset
            )

            # Recognition level basé sur l'ancienneté
            if days_ago > 60:
                recognition_level = random.randint(10, 80)
            elif days_ago > 30:
                recognition_level = random.randint(5, 50)
            elif days_ago > 7:
                recognition_level = random.randint(1, 30)
            else:
                recognition_level = random.randint(0, 10)

            # last_seen : dépend de la fidélité
            if recognition_level > 20:
                last_seen_days_ago = random.randint(0, min(7, days_ago))
            elif recognition_level > 5:
                last_seen_days_ago = random.randint(0, min(30, days_ago))
            else:
                last_seen_days_ago = days_ago

            last_seen = timezone.now() - timedelta(days=last_seen_days_ago)

            # is_verified : clients fidèles plus susceptibles d'être vérifiés
            is_verified = random.random() < (0.3 + (recognition_level / 100 * 0.6))

            # Tags et notes pour qualifier le lead (champs ajoutés en migration 0003)
            tags = random.choice(SAMPLE_TAGS)
            notes = random.choice(SAMPLE_NOTES)

            # Créer le lead (retry en cas de collision MAC/token)
            max_retries = 5
            for attempt in range(max_retries):
                try:
                    extracted_last, extracted_first = _extract_names_from_payload(payload)
                    client = OwnerClient.objects.create(
                        owner=owner,
                        mac_address=mac,
                        email=payload.get('email', '') or None,
                        phone=payload.get('phone') or payload.get('whatsapp', '') or None,
                        first_name=extracted_first or '',
                        last_name=extracted_last or '',
                        payload=payload,
                        client_token=str(uuid.uuid4()),
                        recognition_level=recognition_level,
                        is_verified=is_verified,
                        tags=tags,
                        notes=notes,
                        last_seen=last_seen,
                    )
                    # auto_now_add=True empêche de définir created_at au moment du create()
                    # → on force la date historique via update() direct sur la DB
                    OwnerClient.objects.filter(pk=client.pk).update(created_at=created_at)
                    total_leads += 1
                    leads_by_owner[owner.id] += 1
                    break

                except IntegrityError:
                    # Collision MAC ou token → regénérer et réessayer
                    mac = ':'.join([f'{random.randint(0, 255):02X}' for _ in range(6)])
                    continue

            # Progression
            if (i + 1) % 10 == 0:
                self.stdout.write(f'  → {i + 1}/{total_leads_to_create} leads créés...')

        # Résumé détaillé
        self.stdout.write(self.style.MIGRATE_HEADING('\n' + '='*70))
        self.stdout.write(self.style.SUCCESS(f'✓ {total_schemas} schémas créés'))
        self.stdout.write(self.style.SUCCESS(f'✓ {total_leads} leads créés au total'))

        self.stdout.write(self.style.MIGRATE_HEADING('\nDistribution des leads par propriétaire :'))

        sorted_owners = sorted(leads_by_owner.items(), key=lambda x: x[1], reverse=True)
        owners_map = {o.id: o for o in owners}

        for owner_id, count in sorted_owners:
            owner = owners_map[owner_id]
            percentage = (count / total_leads * 100) if total_leads > 0 else 0
            bar = '█' * int(percentage / 2)
            self.stdout.write(
                f'  {owner.email[:35]:<35} : {count:>3} leads ({percentage:>5.1f}%) {bar}'
            )

        # Statistiques globales
        verified_count = OwnerClient.objects.filter(is_verified=True).count()
        total_all = OwnerClient.objects.count()
        avg_recognition = OwnerClient.objects.aggregate(
            avg=models.Avg('recognition_level')
        )['avg'] or 0
        tagged_count = OwnerClient.objects.exclude(tags=[]).count()

        self.stdout.write(self.style.MIGRATE_HEADING('\nStatistiques globales :'))
        self.stdout.write(
            f'  • Leads vérifiés      : {verified_count}/{total_leads} '
            f'({verified_count / total_leads * 100:.1f}%)'
        )
        self.stdout.write(f'  • Recognition moyen   : {avg_recognition:.1f}')
        self.stdout.write(f'  • Leads avec tags     : {tagged_count}')
        self.stdout.write(
            f'  • Leads dernières 24h : '
            f'{OwnerClient.objects.filter(created_at__gte=timezone.now() - timedelta(hours=24)).count()}'
        )
        self.stdout.write(
            f'  • Leads cette semaine : '
            f'{OwnerClient.objects.filter(created_at__gte=timezone.now() - timedelta(days=7)).count()}'
        )

        self.stdout.write(self.style.MIGRATE_HEADING('='*70))
        self.stdout.write(self.style.SUCCESS('\n✓ Population terminée avec succès !'))
