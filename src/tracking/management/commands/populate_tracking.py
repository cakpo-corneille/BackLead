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
from django.db.models import Sum
from django.utils import timezone

from core_data.models import OwnerClient
from tracking.models import ConnectionSession, TicketPlan

User = get_user_model()


# ---------------------------------------------------------------------------
# Données de référence réalistes (contexte Bénin/Togo)
# ---------------------------------------------------------------------------

PLANS_CATALOGUE = [
    {"name": "Mini Pass",     "price_fcfa": 50,   "duration_minutes": 15},
    {"name": "Pass 30 min",   "price_fcfa": 100,  "duration_minutes": 30},
    {"name": "Pass 1h",       "price_fcfa": 200,  "duration_minutes": 60},
    {"name": "Pass 3h",       "price_fcfa": 500,  "duration_minutes": 180},
    {"name": "Pass Journée",  "price_fcfa": 1000, "duration_minutes": 1440},
    {"name": "Pass Semaine",  "price_fcfa": 5000, "duration_minutes": 10080},
    {"name": "Pass Illimité", "price_fcfa": 2000, "duration_minutes": 1440},
]

DISCONNECT_CAUSES = [
    "session-timeout",   # le plus fréquent — ticket expiré
    "session-timeout",
    "session-timeout",
    "lost-service",      # client a perdu le signal
    "user-request",      # client s'est déconnecté manuellement
    "admin-reset",       # gérant a reseté la session
    "expired-by-server", # Celery a fermé la session
]


IP_RANGES = [
    ("192.168.88.", range(2, 200)),
    ("192.168.1.",  range(100, 250)),
    ("10.0.0.",     range(2, 150)),
    ("172.16.0.",   range(2, 100)),
]

TICKET_PREFIXES = ["TKT", "PASS", "WF", "ZN", "VIP", "DAY", "HR"]


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------

def random_mac():
    return ":".join(f"{random.randint(0, 255):02X}" for _ in range(6))


def random_ip():
    prefix, rng = random.choice(IP_RANGES)
    return f"{prefix}{random.choice(list(rng))}"


def random_ticket_id():
    return f"{random.choice(TICKET_PREFIXES)}-{random.randint(10000, 99999)}"


def random_mikrotik_session_id():
    return "*" + "".join(random.choices("0123456789ABCDEF", k=8))


def random_uptime_seconds(plan):
    """Uptime cohérent avec la durée du plan (entre 20% et 105%)."""
    max_s = plan.duration_minutes * 60
    return random.randint(max(int(max_s * 0.20), 30), int(max_s * 1.05))


def random_bytes(uptime_seconds, is_download=True):
    """Bytes cohérents avec l'uptime. Taux réaliste Afrique de l'Ouest."""
    rate_kbps = random.uniform(50, 300) if is_download else random.uniform(10, 80)
    return int(uptime_seconds * rate_kbps * 1024)


def random_started_at(days_back=90):
    """Date aléatoire pondérée vers les 30 derniers jours et les heures de pointe."""
    weights = [3 if d <= 30 else 1 for d in range(1, days_back + 1)]
    days_ago = random.choices(range(1, days_back + 1), weights=weights)[0]

    hour_weights = [
        1, 1, 0, 0, 0, 1,    # 0h–5h  (nuit)
        2, 4, 6, 5, 4, 5,    # 6h–11h (matin)
        6, 5, 4, 4, 5, 7,    # 12h–17h (après-midi)
        8, 9, 8, 6, 4, 2,    # 18h–23h (soirée, pic)
    ]
    hour   = random.choices(range(24), weights=hour_weights)[0]
    minute = random.randint(0, 59)
    second = random.randint(0, 59)

    base = timezone.now() - timedelta(days=days_ago)
    return base.replace(hour=hour, minute=minute, second=second, microsecond=0)


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
        # 1. Vérifier qu'il y a des owners avec des clients
        # ------------------------------------------------------------------ #
        owners = list(
            User.objects.filter(is_superuser=False, is_verify=True)
            .prefetch_related("collected_data")
        )

        if not owners:
            self.stdout.write(self.style.ERROR(
                "Aucun owner vérifié trouvé. Lancez d'abord :\n"
                "  python manage.py populate_accounts\n"
                "  python manage.py populate_core_data"
            ))
            return

        owners_with_clients = [o for o in owners if o.collected_data.exists()]
        if not owners_with_clients:
            self.stdout.write(self.style.ERROR(
                "Aucun owner n'a de leads. Lancez d'abord :\n"
                "  python manage.py populate_core_data"
            ))
            return

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"Peuplement tracking — {len(owners_with_clients)} owners, "
            f"{n_sessions} sessions demandées"
        ))

        # ------------------------------------------------------------------ #
        # 2. Créer les TicketPlans pour chaque owner
        # ------------------------------------------------------------------ #
        self.stdout.write("\n→ Création des plans tarifaires...")
        plans_by_owner = {}

        for owner in owners_with_clients:
            n_plans = random.randint(2, min(5, len(PLANS_CATALOGUE)))
            selected = random.sample(PLANS_CATALOGUE, n_plans)

            owner_plans = []
            for plan_data in selected:
                plan, created = TicketPlan.objects.get_or_create(
                    owner=owner,
                    name=plan_data["name"],
                    defaults={
                        "price_fcfa":       plan_data["price_fcfa"],
                        "duration_minutes": plan_data["duration_minutes"],
                        "is_active":        random.random() > 0.10,  # 90% actifs
                    },
                )
                owner_plans.append(plan)
                verb = self.style.SUCCESS("créé") if created else self.style.WARNING("existe déjà")
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

        owner_weights = [max(o.collected_data.count(), 1) for o in owners_with_clients]

        sessions_created = 0
        sessions_skipped = 0

        for _ in range(n_sessions):
            owner = random.choices(owners_with_clients, weights=owner_weights, k=1)[0]

            client = owner.collected_data.order_by("?").first()
            if not client:
                sessions_skipped += 1
                continue

            # Plan (None dans ~15% des cas — session sans plan détecté)
            owner_plans = plans_by_owner.get(owner.pk, [])
            plan = random.choice(owner_plans) if owner_plans and random.random() > 0.15 else None

            # Timing
            started_at = random_started_at(days_back=90)
            uptime_s   = random_uptime_seconds(plan) if plan else random.randint(60, 7200)
            b_down     = random_bytes(uptime_s, is_download=True)
            b_up       = random_bytes(uptime_s, is_download=False)

            # MAC : réutiliser celle du client dans 30% des cas
            mac = client.mac_address if (random.random() < 0.30 and client.mac_address) else random_mac()
            ip  = random_ip()

            # État actif / fermé
            time_since_start = timezone.now() - started_at
            if time_since_start.total_seconds() < 7200 and random.random() < 0.40:
                is_active        = True
                ended_at         = None
                disconnect_cause = ''
                last_heartbeat   = timezone.now() - timedelta(seconds=random.randint(0, 300))
            else:
                is_active        = False
                ended_at         = started_at + timedelta(seconds=uptime_s)
                disconnect_cause = random.choice(DISCONNECT_CAUSES)
                last_heartbeat   = ended_at

            # amount_fcfa figé au moment de la session
            amount_fcfa = plan.price_fcfa if plan else 0

            session = ConnectionSession(
                owner=owner,
                client=client,
                ticket_plan=plan,
                amount_fcfa=amount_fcfa,
                mac_address=mac,
                ip_address=ip,
                ticket_id=random_ticket_id() if random.random() < 0.70 else None,
                mikrotik_session_id=random_mikrotik_session_id() if random.random() < 0.60 else None,
                session_key=uuid.uuid4(),
                session_timeout_seconds=plan.duration_minutes * 60 if plan else 0,
                uptime_seconds=uptime_s,
                bytes_downloaded=b_down,
                bytes_uploaded=b_up,
                is_active=is_active,
                ended_at=ended_at,
                disconnect_cause=disconnect_cause,
            )
            session.save()

            # Corriger started_at et last_heartbeat (auto_now_add non surchargeable à la création)
            ConnectionSession.objects.filter(pk=session.pk).update(
                started_at=started_at,
                last_heartbeat=last_heartbeat,
            )

            sessions_created += 1

        self.stdout.write(self.style.SUCCESS(f"  ✓ {sessions_created} sessions créées"))
        if sessions_skipped:
            self.stdout.write(self.style.WARNING(f"  ⚠ {sessions_skipped} sessions ignorées (owner sans clients)"))

        # ------------------------------------------------------------------ #
        # 4. Résumé final
        # ------------------------------------------------------------------ #
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("── Résumé ──"))

        total_sessions  = ConnectionSession.objects.count()
        active_sessions = ConnectionSession.objects.filter(is_active=True).count()
        total_plans_db  = TicketPlan.objects.count()
        revenue         = ConnectionSession.objects.aggregate(
            total=Sum("amount_fcfa")
        )["total"] or 0

        self.stdout.write(f"  Plans tarifaires  : {total_plans_db}")
        self.stdout.write(f"  Sessions totales  : {total_sessions}")
        self.stdout.write(f"  Sessions actives  : {active_sessions}")
        self.stdout.write(f"  Sessions fermées  : {total_sessions - active_sessions}")
        self.stdout.write(f"  Revenue estimé    : {revenue:,} FCFA".replace(",", " "))
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            "Peuplement tracking terminé. Endpoints disponibles :\n"
            "  GET /api/v1/ticket-plans/\n"
            "  GET /api/v1/sessions/\n"
            "  GET /api/v1/tracking-analytics/overview/"
        ))
