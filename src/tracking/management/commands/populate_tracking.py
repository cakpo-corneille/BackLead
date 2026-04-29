"""
Management command pour peupler l'app tracking avec des données de test réalistes.

Usage:
    python manage.py populate_tracking
    python manage.py populate_tracking --sessions 300
    python manage.py populate_tracking --clear
    python manage.py populate_tracking --clear --sessions 500

Options:
    --clear           : Supprimer toutes les sessions et plans existants avant de peupler
    --sessions <n>    : Nombre total de sessions à créer (défaut : 150)
"""
import random
import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from core_data.models import FormSchema, OwnerClient
from tracking.models import ConnectionSession, TicketPlan

User = get_user_model()


# ---------------------------------------------------------------------------
# Données de référence réalistes (contexte Bénin/Togo)
# ---------------------------------------------------------------------------

# Plans tarifaires typiques d'un WiFi Zone béninois
PLANS_CATALOGUE = [
    {
        "name": "Pass 30 min",
        "price_fcfa": 100,
        "duration_minutes": 30,
        "download_limit_mb": 200,
        "upload_limit_mb": 50,
    },
    {
        "name": "Pass 1h",
        "price_fcfa": 200,
        "duration_minutes": 60,
        "download_limit_mb": 500,
        "upload_limit_mb": 100,
    },
    {
        "name": "Pass 3h",
        "price_fcfa": 500,
        "duration_minutes": 180,
        "download_limit_mb": 1500,
        "upload_limit_mb": 300,
    },
    {
        "name": "Pass Journée",
        "price_fcfa": 1000,
        "duration_minutes": 1440,
        "download_limit_mb": None,  # illimité
        "upload_limit_mb": None,
    },
    {
        "name": "Pass Semaine",
        "price_fcfa": 5000,
        "duration_minutes": 10080,
        "download_limit_mb": None,
        "upload_limit_mb": None,
    },
    {
        "name": "Pass Illimité",
        "price_fcfa": 2000,
        "duration_minutes": 1440,
        "download_limit_mb": None,
        "upload_limit_mb": None,
    },
    {
        "name": "Mini Pass",
        "price_fcfa": 50,
        "duration_minutes": 15,
        "download_limit_mb": 80,
        "upload_limit_mb": 20,
    },
]

# User-agents mobiles typiques en Afrique de l'Ouest
USER_AGENTS = [
    "Mozilla/5.0 (Linux; Android 11; Tecno Spark 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 10; TECNO KB8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 12; Samsung SM-A035F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 9; itel A56) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 11; Infinix X688B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 10; Nokia C3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 13; Xiaomi Redmi Note 11) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 8.1.0; HUAWEI Y6 2019) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Linux; Android 11; Oukitel C21 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Mobile Safari/537.36",
    "",  # Certains clients n'envoient pas de user-agent
]

# Plages IP privées typiques MikroTik
IP_RANGES = [
    ("192.168.88.", range(2, 200)),
    ("192.168.1.", range(100, 250)),
    ("10.0.0.", range(2, 150)),
    ("172.16.0.", range(2, 100)),
]

# Préfixes de tickets MikroTik réalistes
TICKET_PREFIXES = ["TKT", "PASS", "WF", "ZN", "VIP", "DAY", "HR"]


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------

def random_mac():
    """Génère une adresse MAC aléatoire au format AA:BB:CC:DD:EE:FF."""
    return ":".join(f"{random.randint(0, 255):02X}" for _ in range(6))


def random_ip():
    """Génère une IP locale réaliste."""
    prefix, rng = random.choice(IP_RANGES)
    return f"{prefix}{random.choice(list(rng))}"


def random_ticket_id():
    """Génère un identifiant de ticket MikroTik réaliste."""
    prefix = random.choice(TICKET_PREFIXES)
    return f"{prefix}-{random.randint(10000, 99999)}"


def random_mikrotik_session_id():
    """Génère un identifiant de session MikroTik (hex)."""
    return "".join(random.choices("0123456789abcdef", k=12))


def random_uptime_seconds(plan):
    """
    Génère un uptime cohérent avec la durée du plan.
    Varie entre 20% et 105% de la durée (légère dérive possible).
    """
    max_seconds = plan.duration_minutes * 60
    low = int(max_seconds * 0.20)
    high = int(max_seconds * 1.05)
    return random.randint(max(low, 30), high)


def random_bytes(uptime_seconds, is_download=True):
    """
    Génère des bytes consommés cohérents avec l'uptime.
    Taux moyen : 50–300 KB/s en download, 10–80 KB/s en upload.
    """
    if is_download:
        rate_kbps = random.uniform(50, 300)
    else:
        rate_kbps = random.uniform(10, 80)
    return int(uptime_seconds * rate_kbps * 1024)


def random_started_at(days_back=90):
    """
    Génère une date de début aléatoire dans les `days_back` derniers jours.
    Pondérée vers les heures de pointe (7h–22h).
    """
    # Décalage en jours (plus de poids sur les 30 derniers jours)
    weights = [3 if d <= 30 else 1 for d in range(1, days_back + 1)]
    days_ago = random.choices(range(1, days_back + 1), weights=weights)[0]

    # Heure (pondération vers les heures de connexion réelles WiFi Zone)
    hour_weights = [
        1, 1, 0, 0, 0, 1,       # 0h-5h  (nuit, très peu)
        2, 4, 6, 5, 4, 5,       # 6h-11h (matin, montée)
        6, 5, 4, 4, 5, 7,       # 12h-17h (après-midi)
        8, 9, 8, 6, 4, 2,       # 18h-23h (soirée, pic)
    ]
    hour = random.choices(range(24), weights=hour_weights)[0]
    minute = random.randint(0, 59)
    second = random.randint(0, 59)

    base = timezone.now() - timedelta(days=days_ago)
    return base.replace(hour=hour, minute=minute, second=second, microsecond=0)


def build_last_raw_data(session_key, mac, ip, uptime_s, b_down, b_up, plan):
    """Reconstruit un snapshot de heartbeat brut réaliste."""

    def fmt_uptime(s):
        d, rem = divmod(s, 86400)
        h, rem = divmod(rem, 3600)
        m, sec = divmod(rem, 60)
        parts = []
        if d:
            parts.append(f"{d}d")
        if h:
            parts.append(f"{h}h")
        if m:
            parts.append(f"{m}m")
        parts.append(f"{sec}s")
        return "".join(parts)

    def fmt_limit(mb):
        if mb is None:
            return "---"
        if mb >= 1024:
            return f"{mb // 1024}M"
        return f"{mb}k"

    data = {
        "mac_address": mac,
        "ip_address": ip,
        "uptime": fmt_uptime(uptime_s),
        "bytes_in": str(b_down),
        "bytes_out": str(b_up),
        "session_key": str(session_key),
    }
    if plan:
        data["rx_limit"] = fmt_limit(plan.download_limit_mb)
        data["tx_limit"] = fmt_limit(plan.upload_limit_mb)
    else:
        data["rx_limit"] = "---"
        data["tx_limit"] = "---"
    return data


# ---------------------------------------------------------------------------
# Commande principale
# ---------------------------------------------------------------------------

class Command(BaseCommand):
    help = "Peuple l'app tracking avec des plans tarifaires et sessions WiFi réalistes"

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Supprimer tous les plans et sessions existants avant de peupler",
        )
        parser.add_argument(
            "--sessions",
            type=int,
            default=150,
            help="Nombre total de sessions à créer (défaut : 150)",
        )

    def handle(self, *args, **options):
        n_sessions = options["sessions"]

        # ------------------------------------------------------------------ #
        # 0. Clear optionnel
        # ------------------------------------------------------------------ #
        if options["clear"]:
            self.stdout.write(self.style.WARNING("Suppression des données tracking existantes..."))
            ConnectionSession.objects.all().delete()
            TicketPlan.objects.all().delete()
            self.stdout.write(self.style.SUCCESS("  ✓ Sessions et plans supprimés"))

        # ------------------------------------------------------------------ #
        # 1. Vérifier qu'il y a des owners et des OwnerClients
        # ------------------------------------------------------------------ #
        owners = list(
            User.objects.filter(is_superuser=False, is_verify=True)
            .prefetch_related("collected_data", "form_schema")
        )

        if not owners:
            self.stdout.write(
                self.style.ERROR(
                    "Aucun owner vérifié trouvé. Lancez d'abord :\n"
                    "  python manage.py populate_accounts\n"
                    "  python manage.py populate_core_data"
                )
            )
            return

        # Ne garder que les owners qui ont au moins un OwnerClient
        owners_with_clients = [
            o for o in owners if o.collected_data.exists()
        ]
        if not owners_with_clients:
            self.stdout.write(
                self.style.ERROR(
                    "Aucun owner n'a de leads. Lancez d'abord :\n"
                    "  python manage.py populate_core_data"
                )
            )
            return

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Peuplement tracking — {len(owners_with_clients)} owners, "
                f"{n_sessions} sessions demandées"
            )
        )

        # ------------------------------------------------------------------ #
        # 2. Créer les TicketPlans pour chaque owner
        # ------------------------------------------------------------------ #
        self.stdout.write("\n→ Création des plans tarifaires...")
        plans_by_owner = {}

        for owner in owners_with_clients:
            # Chaque owner reçoit entre 2 et 5 plans tirés au sort du catalogue
            n_plans = random.randint(2, min(5, len(PLANS_CATALOGUE)))
            selected = random.sample(PLANS_CATALOGUE, n_plans)

            owner_plans = []
            for plan_data in selected:
                plan, created = TicketPlan.objects.get_or_create(
                    owner=owner,
                    name=plan_data["name"],
                    defaults={
                        "price_fcfa": plan_data["price_fcfa"],
                        "duration_minutes": plan_data["duration_minutes"],
                        "download_limit_mb": plan_data["download_limit_mb"],
                        "upload_limit_mb": plan_data["upload_limit_mb"],
                        "is_active": random.random() > 0.10,  # 90% actifs
                    },
                )
                owner_plans.append(plan)
                if created:
                    verb = self.style.SUCCESS("créé")
                else:
                    verb = self.style.WARNING("existe déjà")
                self.stdout.write(
                    f"   [{verb}] {owner.email[:28]:<28} — {plan.name} "
                    f"({plan.price_fcfa} FCFA / {plan.duration_minutes} min)"
                )

            plans_by_owner[owner.pk] = owner_plans

        total_plans = sum(len(p) for p in plans_by_owner.values())
        self.stdout.write(self.style.SUCCESS(f"  ✓ {total_plans} plans créés ou existants"))

        # ------------------------------------------------------------------ #
        # 3. Créer les ConnectionSessions
        # ------------------------------------------------------------------ #
        self.stdout.write(f"\n→ Création de {n_sessions} sessions WiFi...")

        # Répartition pondérée : plus de sessions pour les owners actifs
        owner_weights = []
        for o in owners_with_clients:
            client_count = o.collected_data.count()
            owner_weights.append(max(client_count, 1))

        sessions_created = 0
        sessions_skipped = 0

        for _ in range(n_sessions):
            # Choisir un owner proportionnellement à son nombre de leads
            owner = random.choices(owners_with_clients, weights=owner_weights, k=1)[0]

            # Choisir un lead existant de cet owner
            client = owner.collected_data.order_by("?").first()
            if not client:
                sessions_skipped += 1
                continue

            # Choisir un plan (ou None — sessions sans plan détecté, ~15%)
            owner_plans = plans_by_owner.get(owner.pk, [])
            if owner_plans and random.random() > 0.15:
                plan = random.choice(owner_plans)
            else:
                plan = None

            # Timing
            started_at = random_started_at(days_back=90)

            # Uptime cohérent avec le plan
            if plan:
                uptime_s = random_uptime_seconds(plan)
            else:
                uptime_s = random.randint(60, 7200)  # entre 1 min et 2h

            # Bytes cohérents avec l'uptime
            b_down = random_bytes(uptime_s, is_download=True)
            b_up = random_bytes(uptime_s, is_download=False)

            # Limites depuis le plan (en bytes)
            dl_limit = plan.download_limit_bytes if plan else None
            ul_limit = plan.upload_limit_bytes if plan else None

            # MAC : utiliser celle du client (réaliste) ou en générer une nouvelle
            # (~30% de chance de réutiliser la MAC du client pour simuler
            # plusieurs sessions du même appareil)
            if random.random() < 0.30 and client.mac_address:
                mac = client.mac_address
            else:
                mac = random_mac()

            ip = random_ip()
            session_key = uuid.uuid4()

            # La session est-elle encore active ?
            # Sessions récentes (< 2h) : 40% de chance d'être actives
            # Sessions anciennes : toujours fermées
            time_since_start = timezone.now() - started_at
            if time_since_start.total_seconds() < 7200 and random.random() < 0.40:
                is_active = True
                ended_at = None
                last_heartbeat = timezone.now() - timedelta(seconds=random.randint(0, 300))
            else:
                is_active = False
                ended_at = started_at + timedelta(seconds=uptime_s)
                last_heartbeat = ended_at

            # User-agent
            ua = random.choice(USER_AGENTS)

            # Ticket ID et session MikroTik (optionnels, ~70% des sessions)
            ticket_id = random_ticket_id() if random.random() < 0.70 else None
            mikrotik_sid = random_mikrotik_session_id() if random.random() < 0.60 else None

            # Raw data snapshot
            raw_data = build_last_raw_data(
                session_key, mac, ip, uptime_s, b_down, b_up, plan
            )

            # Création via queryset direct (pas via handle_heartbeat pour ne
            # pas dépendre du rate-limiter ni de la logique de résolution de
            # FormSchema en test)
            session = ConnectionSession(
                owner=owner,
                client=client,
                ticket_plan=plan,
                mac_address=mac,
                ip_address=ip,
                ticket_id=ticket_id,
                mikrotik_session_id=mikrotik_sid,
                session_key=session_key,
                uptime_seconds=uptime_s,
                bytes_downloaded=b_down,
                bytes_uploaded=b_up,
                download_limit_bytes=dl_limit,
                upload_limit_bytes=ul_limit,
                is_active=is_active,
                ended_at=ended_at,
                user_agent=ua,
                last_raw_data=raw_data,
            )
            # On bypasse auto_now_add pour started_at et last_heartbeat
            session.save()

            # Corriger started_at et last_heartbeat après save
            # (auto_now_add/auto_now ne peuvent pas être surchargés à la création)
            ConnectionSession.objects.filter(pk=session.pk).update(
                started_at=started_at,
                last_heartbeat=last_heartbeat,
            )

            sessions_created += 1

        self.stdout.write(
            self.style.SUCCESS(f"  ✓ {sessions_created} sessions créées")
        )
        if sessions_skipped:
            self.stdout.write(
                self.style.WARNING(f"  ⚠ {sessions_skipped} sessions ignorées (owner sans clients)")
            )

        # ------------------------------------------------------------------ #
        # 4. Résumé final
        # ------------------------------------------------------------------ #
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("── Résumé ──"))

        total_sessions = ConnectionSession.objects.count()
        active_sessions = ConnectionSession.objects.filter(is_active=True).count()
        total_ticket_plans = TicketPlan.objects.count()

        # Revenue estimé total
        from django.db.models import Sum
        revenue = (
            ConnectionSession.objects.filter(ticket_plan__isnull=False)
            .aggregate(total=Sum("ticket_plan__price_fcfa"))["total"]
            or 0
        )

        self.stdout.write(f"  Plans tarifaires  : {total_ticket_plans}")
        self.stdout.write(f"  Sessions totales  : {total_sessions}")
        self.stdout.write(f"  Sessions actives  : {active_sessions}")
        self.stdout.write(f"  Sessions fermées  : {total_sessions - active_sessions}")
        self.stdout.write(f"  Revenue estimé    : {revenue:,} FCFA".replace(",", " "))
        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                "Peuplement tracking terminé. Vous pouvez tester les endpoints :\n"
                "  GET /api/v1/ticket-plans/\n"
                "  GET /api/v1/sessions/\n"
                "  GET /api/v1/session-analytics/overview/"
            )
        )
