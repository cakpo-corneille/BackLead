"""
Management command pour peupler l'app accounts avec des données de test réalistes.

Usage:
    python manage.py populate_accounts
Options:
    --clear : Supprimer toutes les données existantes avant de peupler
"""
import os
import random
from io import BytesIO
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from accounts.models import OwnerProfile

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

User = get_user_model()


class Command(BaseCommand):
    help = 'Peuple la base de données avec des utilisateurs et profils de test réalistes'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Supprimer toutes les données existantes avant de peupler',
        )

    def handle(self, *args, **options):
        if options['clear']:
            self.stdout.write(self.style.WARNING('Suppression des données existantes...'))
            User.objects.filter(is_superuser=False).delete()
            self.stdout.write(self.style.SUCCESS('✓ Données supprimées'))

        self.stdout.write(self.style.MIGRATE_HEADING('Création des utilisateurs de test...'))

        # Données réalistes pour le Bénin
        owners_data = [
            {
                'email': 'cafe.akpakpa@example.com',
                'password': 'CafePass123',
                'business_name': 'Café des Palmes',
                'nom': 'Koffi',
                'prenom': 'Yves',
                'phone_contact': '+22997123456',
                'whatsapp_contact': '+22997123456',
                'pays': 'Bénin',
                'ville': 'Cotonou',
                'quartier': 'Akpakpa',
                'main_goal': 'collect_leads',
                'logo_color': '#E74C3C',
                'logo_text': 'CP',
            },
            {
                'email': 'restaurant.marina@example.com',
                'password': 'RestauPass1',
                'business_name': 'Restaurant Marina',
                'nom': 'Dossou',
                'prenom': 'Marie',
                'phone_contact': '+22996234567',
                'whatsapp_contact': '+22996234567',
                'pays': 'Bénin',
                'ville': 'Cotonou',
                'quartier': 'Ganhi',
                'main_goal': 'analytics',
                'logo_color': '#3498DB',
                'logo_text': 'RM',
            },
            {
                'email': 'hotel.benin@example.com',
                'password': 'HotelPass1',
                'business_name': 'Hôtel du Bénin',
                'nom': 'Agbodjan',
                'prenom': 'Pascal',
                'phone_contact': '+22995345678',
                'whatsapp_contact': '+22995345678',
                'pays': 'Bénin',
                'ville': 'Cotonou',
                'quartier': 'Haie Vive',
                'main_goal': 'marketing',
                'logo_color': '#2ECC71',
                'logo_text': 'HB',
            },
            {
                'email': 'bar.fidjrosse@example.com',
                'password': 'BarPass123',
                'business_name': 'Bar Le Rendez-vous',
                'nom': 'Hounsou',
                'prenom': 'Jean',
                'phone_contact': '+22994456789',
                'whatsapp_contact': '+22994456789',
                'pays': 'Bénin',
                'ville': 'Cotonou',
                'quartier': 'Fidjrossè',
                'main_goal': 'collect_leads',
                'logo_color': '#9B59B6',
                'logo_text': 'RV',
            },
            {
                'email': 'salon.coiffure@example.com',
                'password': 'SalonPass1',
                'business_name': 'Salon Beauté Divine',
                'nom': 'Assogba',
                'prenom': 'Sylvie',
                'phone_contact': '+22993567890',
                'whatsapp_contact': '+22993567890',
                'pays': 'Bénin',
                'ville': 'Cotonou',
                'quartier': 'Cadjèhoun',
                'main_goal': 'collect_leads',
                'logo_color': '#F39C12',
                'logo_text': 'BD',
            },
            {
                'email': 'boutique.mode@example.com',
                'password': 'BoutiqueP1',
                'business_name': 'Boutique Élégance',
                'nom': 'Sossou',
                'prenom': 'Rachelle',
                'phone_contact': '+22992678901',
                'whatsapp_contact': '+22992678901',
                'pays': 'Bénin',
                'ville': 'Cotonou',
                'quartier': 'Jonquet',
                'main_goal': 'marketing',
                'logo_color': '#E91E63',
                'logo_text': 'BE',
            },
            {
                'email': 'pizzeria.porto@example.com',
                'password': 'PizzaPass1',
                'business_name': 'Pizzeria Porto-Novo',
                'nom': 'Lokossou',
                'prenom': 'Marc',
                'phone_contact': '+22991789012',
                'whatsapp_contact': '+22991789012',
                'pays': 'Bénin',
                'ville': 'Porto-Novo',
                'quartier': 'Ouando',
                'main_goal': 'collect_leads',
                'logo_color': '#FF5722',
                'logo_text': 'PP',
            },
            {
                'email': 'gym.fitness@example.com',
                'password': 'GymPass123',
                'business_name': 'Fitness Club',
                'nom': 'Zannou',
                'prenom': 'Eric',
                'phone_contact': '+22990890123',
                'whatsapp_contact': '+22990890123',
                'pays': 'Bénin',
                'ville': 'Cotonou',
                'quartier': 'Cocotiers',
                'main_goal': 'analytics',
                'logo_color': '#607D8B',
                'logo_text': 'FC',
            },
            {
                'email': 'librairie.savoir@example.com',
                'password': 'LibraPass1',
                'business_name': 'Librairie du Savoir',
                'nom': 'Gbaguidi',
                'prenom': 'Lucie',
                'phone_contact': '+22989901234',
                'whatsapp_contact': '+22989901234',
                'pays': 'Bénin',
                'ville': 'Cotonou',
                'quartier': 'Zongo',
                'main_goal': 'collect_leads',
                'logo_color': '#795548',
                'logo_text': 'LS',
            },
            {
                'email': 'clinique.sante@example.com',
                'password': 'CliniqueP1',
                'business_name': 'Clinique Santé Plus',
                'nom': 'Ahouandjinou',
                'prenom': 'Serge',
                'phone_contact': '+22988012345',
                'whatsapp_contact': '+22988012345',
                'pays': 'Bénin',
                'ville': 'Cotonou',
                'quartier': 'Gbégamey',
                'main_goal': 'analytics',
                'logo_color': '#009688',
                'logo_text': 'SP',
            },
            {
                'email': 'hotel.parakou@example.com',
                'password': 'ParakouP1',
                'business_name': 'Hôtel Parakou Palace',
                'nom': 'Olouwa',
                'prenom': 'Fatima',
                'phone_contact': '+22997765432',
                'whatsapp_contact': '+22997765432',
                'pays': 'Bénin',
                'ville': 'Parakou',
                'quartier': 'Zongo-Kpèbié',
                'main_goal': 'marketing',
                'logo_color': '#1ABC9C',
                'logo_text': 'HP',
            },
            {
                'email': 'maquis.ouidah@example.com',
                'password': 'OuidahP12',
                'business_name': 'Maquis Bord de Mer',
                'nom': 'Aïzannon',
                'prenom': 'Gildas',
                'phone_contact': '+22996543210',
                'whatsapp_contact': '+22996543210',
                'pays': 'Bénin',
                'ville': 'Ouidah',
                'quartier': 'Docomé',
                'main_goal': 'collect_leads',
                'logo_color': '#16A085',
                'logo_text': 'MB',
            },
        ]

        created_count = 0
        error_count = 0

        for owner_data in owners_data:
            try:
                # Vérifier si l'utilisateur existe déjà
                if User.objects.filter(email=owner_data['email']).exists():
                    self.stdout.write(
                        self.style.WARNING(
                            f'⚠ Ignoré (existe déjà) : {owner_data["email"]}'
                        )
                    )
                    continue

                # Extraire les données pour le logo
                logo_color = owner_data.pop('logo_color')
                logo_text = owner_data.pop('logo_text')

                # Créer l'utilisateur
                user = User.objects.create_user(
                    email=owner_data['email'],
                    password=owner_data['password']
                )

                # Marquer comme vérifié pour les tests
                user.is_verify = True
                user.save()

                # Récupérer le profil créé automatiquement par le signal
                profile = user.profile

                # Mettre à jour le profil avec les données
                profile.business_name = owner_data['business_name']
                profile.nom = owner_data['nom']
                profile.prenom = owner_data['prenom']
                profile.phone_contact = owner_data['phone_contact']
                profile.whatsapp_contact = owner_data['whatsapp_contact']
                profile.pays = owner_data['pays']
                profile.ville = owner_data['ville']
                profile.quartier = owner_data['quartier']
                profile.main_goal = owner_data['main_goal']

                # Générer et attacher le logo
                if PIL_AVAILABLE:
                    logo_file = self.generate_logo(logo_text, logo_color)
                    profile.logo.save(
                        f'{owner_data["business_name"].lower().replace(" ", "_")}_logo.png',
                        logo_file,
                        save=False
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING(
                            f'⚠ PIL non disponible - logo par défaut utilisé pour {owner_data["business_name"]}'
                        )
                    )

                profile.save()  # Déclenche le calcul de is_complete et pass_onboarding

                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f'✓ Créé : {owner_data["business_name"]} ({owner_data["email"]}) | '
                        f'Complet : {profile.is_complete} | Onboarding : {profile.pass_onboarding}'
                    )
                )

            except Exception as e:
                error_count += 1
                self.stdout.write(
                    self.style.ERROR(
                        f'✗ Erreur pour {owner_data.get("email", "unknown")} : {str(e)}'
                    )
                )

        # Résumé
        self.stdout.write(self.style.MIGRATE_HEADING('\n' + '='*60))
        self.stdout.write(
            self.style.SUCCESS(
                f'✓ {created_count} propriétaires créés avec succès'
            )
        )

        if error_count > 0:
            self.stdout.write(
                self.style.ERROR(
                    f'✗ {error_count} erreurs rencontrées'
                )
            )

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                '\nIdentifiants de connexion :'
            )
        )
        self.stdout.write('  • cafe.akpakpa@example.com        → CafePass123')
        self.stdout.write('  • restaurant.marina@example.com   → RestauPass1')
        self.stdout.write('  • hotel.benin@example.com         → HotelPass1')
        self.stdout.write('  • bar.fidjrosse@example.com       → BarPass123')
        self.stdout.write('  • salon.coiffure@example.com      → SalonPass1')
        self.stdout.write('  • boutique.mode@example.com       → BoutiqueP1')
        self.stdout.write('  • pizzeria.porto@example.com      → PizzaPass1')
        self.stdout.write('  • gym.fitness@example.com         → GymPass123')
        self.stdout.write('  • librairie.savoir@example.com    → LibraPass1')
        self.stdout.write('  • clinique.sante@example.com      → CliniqueP1')
        self.stdout.write('  • hotel.parakou@example.com       → ParakouP1')
        self.stdout.write('  • maquis.ouidah@example.com       → OuidahP12')
        self.stdout.write(self.style.MIGRATE_HEADING('='*60))

    def generate_logo(self, text, bg_color):
        """
        Génère un logo simple avec les initiales sur fond coloré.

        Args:
            text (str): Texte à afficher (généralement 2 lettres)
            bg_color (str): Couleur de fond en hexadécimal (ex: '#3498DB')

        Returns:
            ContentFile: Fichier image prêt à être sauvegardé
        """
        if not PIL_AVAILABLE:
            self.stdout.write(
                self.style.WARNING('PIL non disponible - installation de Pillow recommandée')
            )
            return self._generate_placeholder_logo()

        try:
            # Dimensions du logo
            size = (400, 400)

            # Créer l'image
            image = Image.new('RGB', size, bg_color)
            draw = ImageDraw.Draw(image)

            # Essayer plusieurs polices dans l'ordre de préférence
            font = None
            font_paths = [
                '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
                '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
                '/System/Library/Fonts/Helvetica.ttc',
                '/Library/Fonts/Arial.ttf',
                'C:\\Windows\\Fonts\\arial.ttf',
            ]

            font_size = 180

            for path in font_paths:
                if os.path.exists(path):
                    try:
                        font = ImageFont.truetype(path, font_size)
                        break
                    except Exception:
                        continue

            # Fallback : police par défaut
            if not font:
                try:
                    font = ImageFont.load_default()
                    text = text[:2].upper()
                except Exception:
                    return self._generate_placeholder_logo(bg_color)

            # Calculer la position pour centrer le texte
            try:
                bbox = draw.textbbox((0, 0), text, font=font)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]
            except Exception:
                text_width, text_height = draw.textsize(text, font=font)

            position = (
                (size[0] - text_width) // 2,
                (size[1] - text_height) // 2 - 20
            )

            # Dessiner le texte en blanc
            draw.text(position, text, fill='white', font=font)

            # Sauvegarder dans un buffer
            buffer = BytesIO()
            image.save(buffer, format='PNG')
            buffer.seek(0)

            return ContentFile(buffer.read())

        except Exception as e:
            self.stdout.write(
                self.style.WARNING(
                    f'Erreur génération logo avec PIL : {e} - Utilisation placeholder'
                )
            )
            return self._generate_placeholder_logo(bg_color)

    def _generate_placeholder_logo(self, bg_color='#CCCCCC'):
        """
        Génère un logo placeholder simple en cas d'erreur.

        Args:
            bg_color (str): Couleur de fond

        Returns:
            ContentFile: Logo placeholder
        """
        try:
            from PIL import Image
            buffer = BytesIO()
            image = Image.new('RGB', (400, 400), bg_color)
            image.save(buffer, format='PNG')
            buffer.seek(0)
            return ContentFile(buffer.read())
        except Exception:
            return ContentFile(b'')
