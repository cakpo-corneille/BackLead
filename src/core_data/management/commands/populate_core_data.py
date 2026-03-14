"""
Management command pour peupler l'app core_data avec des données de test réalistes.

Usage:
    python manage.py populate_core_data

Options:
    --clear : Supprimer toutes les données existantes avant de peupler
    --leads <nombre> : Nombre total de leads à créer (défaut: 100)
"""
import random
import uuid
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db import IntegrityError,models
from core_data.models import FormSchema, OwnerClient
from faker import Faker

User = get_user_model()


class Command(BaseCommand):
    help = 'Peuple la base de données avec des schémas de formulaires et des leads de test'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Supprimer toutes les données core_data existantes',
        )
        parser.add_argument(
            '--leads',
            type=int,
            default=100,
            help='Nombre total de leads à créer (défaut: 100)',
        )

    def handle(self, *args, **options):
        fake = Faker(['fr_FR'])  # Locale française pour des noms réalistes
        
        if options['clear']:
            self.stdout.write(self.style.WARNING('Suppression des données core_data existantes...'))
            OwnerClient.objects.all().delete()
            self.stdout.write(self.style.SUCCESS('✓ Leads supprimés'))

        total_leads_to_create = options['leads']

        # Récupérer tous les utilisateurs non-superuser
        owners = list(User.objects.filter(is_superuser=False))

        if not owners:
            self.stdout.write(
                self.style.ERROR(
                    '✗ Aucun propriétaire trouvé. Créez d\'abord des utilisateurs.'
                )
            )
            return

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f'Création de {total_leads_to_create} leads pour {len(owners)} propriétaires...'
            )
        )

        # Schémas de formulaires variés
        schemas = [
            {
                'name': 'Formulaire Simple',
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
                'schema': {
                    'fields': [
                        {'name': 'nom', 'label': 'Nom', 'type': 'text', 'required': True},
                        {'name': 'prenom', 'label': 'Prénom', 'type': 'text', 'required': True},
                        {'name': 'email', 'label': 'Email', 'type': 'email', 'required': True},
                        {'name': 'phone', 'label': 'Téléphone', 'type': 'phone', 'required': True},
                        {'name': 'source', 'label': 'Comment nous avez-vous connu ?', 'type': 'choice', 
                         'choices': ['Facebook', 'Instagram', 'Google', 'Bouche-à-oreille', 'Autre'], 'required': False},
                    ]
                }
            },
            {
                'name': 'Formulaire Marketing',
                'schema': {
                    'fields': [
                        {'name': 'nom_complet', 'label': 'Nom complet', 'type': 'text', 'required': True},
                        {'name': 'email', 'label': 'Adresse email', 'type': 'email', 'required': True},
                        {'name': 'phone', 'label': 'WhatsApp', 'type': 'phone', 'required': False},
                        {'name': 'ville', 'label': 'Ville', 'type': 'text', 'required': False},
                        {'name': 'interet', 'label': 'Intérêt principal', 'type': 'choice', 
                         'choices': ['Produits', 'Services', 'Événements', 'Partenariat'], 'required': False},
                    ]
                }
            },
            {
                'name': 'Formulaire Restaurant',
                'schema': {
                    'fields': [
                        {'name': 'nom', 'label': 'Nom', 'type': 'text', 'required': True},
                        {'name': 'email', 'label': 'Email', 'type': 'email', 'required': True},
                        {'name': 'phone', 'label': 'Téléphone', 'type': 'phone', 'required': True},
                        {'name': 'preference', 'label': 'Préférence culinaire', 'type': 'choice',
                         'choices': ['Africain', 'Européen', 'Asiatique', 'Végétarien'], 'required': False},
                    ]
                }
            },
        ]

        villes_benin = [
            'Cotonou', 'Porto-Novo', 'Parakou', 'Abomey-Calavi', 'Djougou',
            'Bohicon', 'Natitingou', 'Ouidah', 'Lokossa', 'Abomey', 'Savalou',
            'Nikki', 'Kandi', 'Malanville', 'Sakété'
        ]

        sources = ['Facebook', 'Instagram', 'Google', 'Bouche-à-oreille', 'Affiche', 'Recommandation', 'LinkedIn']
        interets = ['Produits', 'Services', 'Événements', 'Partenariat', 'Information', 'Autre']
        preferences_culinaires = ['Africain', 'Européen', 'Asiatique', 'Végétarien', 'Fast-food']

        total_schemas = 0
        total_leads = 0
        leads_by_owner = {owner.id: 0 for owner in owners}

        # Assigner un schéma à chaque owner
        for owner in owners:
            schema_data = random.choice(schemas)
            schema, created = FormSchema.objects.update_or_create(
                owner=owner,
                defaults={
                    'name': schema_data['name'],
                    'schema': schema_data['schema'],
                    'double_opt_enable': random.choice([True, False]),
                    'preferred_channel': random.choice(['email', 'phone'])
                }
            )

            if created:
                total_schemas += 1

            self.stdout.write(
                self.style.SUCCESS(
                    f'✓ Schéma "{schema_data["name"]}" assigné à {owner.email}'
                )
            )

        # Créer les leads avec distribution aléatoire et injuste
        self.stdout.write(self.style.MIGRATE_HEADING('\nCréation des leads...'))
        
        # Distribution injuste : quelques owners ont beaucoup de leads, d'autres peu
        # Utiliser une distribution de Pareto (80/20)
        weights = [random.paretovariate(1.5) for _ in owners]
        total_weight = sum(weights)
        normalized_weights = [w / total_weight for w in weights]

        for i in range(total_leads_to_create):
            # Choisir un owner selon la distribution pondérée
            owner = random.choices(owners, weights=normalized_weights)[0]
            schema = FormSchema.objects.get(owner=owner)
            
            # Générer des données réalistes avec Faker
            first_name = fake.first_name()
            last_name = fake.last_name()
            full_name = f'{first_name} {last_name}'
            
            # Email unique
            email_domain = random.choice(['gmail.com', 'yahoo.fr', 'hotmail.com', 'outlook.com', 'protonmail.com'])
            email = f'{fake.user_name()}{random.randint(1, 999)}@{email_domain}'
            
            # Numéro béninois valide
            phone_prefix = random.choice(['97', '96', '95', '94', '93', '92', '91', '90'])
            phone = f'+229{phone_prefix}{random.randint(100000, 999999)}'
            
            # MAC address unique
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
                    # 95% ont un email
                    payload['email'] = email if random.random() > 0.05 else ''
                elif field_name in ['phone', 'whatsapp']:
                    # 85% ont un téléphone
                    payload[field_name] = phone if random.random() > 0.15 else ''
                elif field_name == 'source':
                    payload['source'] = random.choice(sources)
                elif field_name == 'ville':
                    payload['ville'] = random.choice(villes_benin)
                elif field_name == 'interet':
                    payload['interet'] = random.choice(interets)
                elif field_name == 'preference':
                    payload['preference'] = random.choice(preferences_culinaires)
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

            # Recognition level basé sur l'ancienneté et le hasard
            # Anciens clients ont plus de chances d'avoir un recognition_level élevé
            if days_ago > 60:
                recognition_level = random.randint(10, 80)
            elif days_ago > 30:
                recognition_level = random.randint(5, 50)
            elif days_ago > 7:
                recognition_level = random.randint(1, 30)
            else:
                recognition_level = random.randint(0, 10)

            # Clients fidèles reviennent régulièrement
            if recognition_level > 20:
                # Client fidèle : last_seen récent
                last_seen_days_ago = random.randint(0, min(7, days_ago))
            elif recognition_level > 5:
                # Client occasionnel
                last_seen_days_ago = random.randint(0, min(30, days_ago))
            else:
                # Nouveau client ou inactif
                last_seen_days_ago = days_ago

            last_seen = timezone.now() - timedelta(days=last_seen_days_ago)

            # is_verified : clients fidèles plus susceptibles d'être vérifiés
            is_verified = random.random() < (0.3 + (recognition_level / 100 * 0.6))

            # Créer le lead
            max_retries = 5
            for attempt in range(max_retries):
                try:
                    lead = OwnerClient.objects.create(
                        owner=owner,
                        mac_address=mac,
                        email=payload.get('email', '') or None,
                        phone=payload.get('phone') or payload.get('whatsapp', '') or None,
                        payload=payload,
                        client_token=str(uuid.uuid4()),
                        recognition_level=recognition_level,
                        is_verified=is_verified,
                        created_at=created_at,
                        last_seen=last_seen,
                    )
                    total_leads += 1
                    leads_by_owner[owner.id] += 1
                    break

                except IntegrityError:
                    # En cas de duplicate MAC ou token, regénérer
                    mac = ':'.join([f'{random.randint(0, 255):02X}' for _ in range(6)])
                    continue

            # Afficher la progression tous les 10 leads
            if (i + 1) % 10 == 0:
                self.stdout.write(f'  → {i + 1}/{total_leads_to_create} leads créés...')

        # Résumé détaillé
        self.stdout.write(self.style.MIGRATE_HEADING('\n' + '='*70))
        self.stdout.write(self.style.SUCCESS(f'✓ {total_schemas} schémas créés/mis à jour'))
        self.stdout.write(self.style.SUCCESS(f'✓ {total_leads} leads créés au total'))
        
        self.stdout.write(self.style.MIGRATE_HEADING('\nDistribution des leads par propriétaire:'))
        
        # Trier par nombre de leads décroissant
        sorted_owners = sorted(leads_by_owner.items(), key=lambda x: x[1], reverse=True)
        
        for owner_id, count in sorted_owners:
            owner = next(o for o in owners if o.id == owner_id)
            percentage = (count / total_leads * 100) if total_leads > 0 else 0
            bar = '█' * int(percentage / 2)
            
            self.stdout.write(
                f'  {owner.email[:30]:<30} : {count:>3} leads ({percentage:>5.1f}%) {bar}'
            )
        
        # Statistiques supplémentaires
        verified_count = OwnerClient.objects.filter(is_verified=True).count()
        avg_recognition = OwnerClient.objects.aggregate(
            avg=models.Avg('recognition_level')
        )['avg'] or 0
        
        self.stdout.write(self.style.MIGRATE_HEADING('\nStatistiques globales:'))
        self.stdout.write(f'  • Leads vérifiés : {verified_count}/{total_leads} ({verified_count/total_leads*100:.1f}%)')
        self.stdout.write(f'  • Recognition moyen : {avg_recognition:.1f}')
        self.stdout.write(f'  • Leads dernières 24h : {OwnerClient.objects.filter(created_at__gte=timezone.now()-timedelta(hours=24)).count()}')
        self.stdout.write(f'  • Leads cette semaine : {OwnerClient.objects.filter(created_at__gte=timezone.now()-timedelta(days=7)).count()}')
        
        self.stdout.write(self.style.MIGRATE_HEADING('='*70))
        self.stdout.write(self.style.SUCCESS('\n✓ Population terminée avec succès !'))