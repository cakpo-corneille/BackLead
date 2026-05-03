import hashlib
from decimal import Decimal
from django.db import models
from django.utils import timezone
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType


class FeatureFlag(models.Model):
    """
    Feature flags pour activer/desactiver des fonctionnalites.
    Supporte le rollout progressif et le ciblage par plan/owner.
    """
    key = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="Cle",
        help_text="Identifiant unique: new_dashboard, beta_analytics, etc."
    )
    name = models.CharField(max_length=200, verbose_name="Nom")
    description = models.TextField(blank=True, verbose_name="Description")
    
    # Activation globale
    is_enabled = models.BooleanField(default=False, verbose_name="Active globalement")
    
    # Ciblage par plan
    enabled_for_plans = models.ManyToManyField(
        'subscriptions.Plan',
        blank=True,
        related_name='feature_flags',
        verbose_name="Plans actives"
    )
    
    # Ciblage par owner specifique
    enabled_for_owners = models.ManyToManyField(
        'accounts.Owner',
        blank=True,
        related_name='feature_flags',
        verbose_name="Owners actives"
    )
    
    # Rollout progressif (0-100%)
    rollout_percentage = models.PositiveIntegerField(
        default=0,
        verbose_name="Pourcentage de rollout",
        help_text="0-100. Les owners sont selectionnes de maniere deterministe."
    )
    
    # Metadata
    metadata = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Feature Flag"
        verbose_name_plural = "Feature Flags"
        ordering = ['key']

    def __str__(self):
        status = "ON" if self.is_enabled else f"{self.rollout_percentage}%"
        return f"{self.key} ({status})"
    
    def is_enabled_for(self, owner) -> bool:
        """
        Verifie si le flag est active pour un owner specifique.
        
        Ordre de verification:
        1. Activation globale
        2. Owner dans la liste explicite
        3. Plan de l'owner dans la liste des plans
        4. Rollout progressif (hash deterministe)
        """
        # 1. Activation globale
        if self.is_enabled:
            return True
        
        # 2. Owner explicitement active
        if self.enabled_for_owners.filter(pk=owner.pk).exists():
            return True
        
        # 3. Plan active
        subscription = getattr(owner, 'subscription', None)
        if subscription and self.enabled_for_plans.filter(pk=subscription.plan_id).exists():
            return True
        
        # 4. Rollout progressif
        if self.rollout_percentage > 0:
            # Hash deterministe base sur owner_id + flag_key
            hash_input = f"{owner.pk}:{self.key}"
            hash_value = int(hashlib.md5(hash_input.encode()).hexdigest(), 16)
            owner_percentage = hash_value % 100
            return owner_percentage < self.rollout_percentage
        
        return False


class SystemConfig(models.Model):
    """
    Configuration systeme dynamique (key-value store).
    Permet de modifier des parametres sans redeployer.
    """
    key = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="Cle",
        help_text="Ex: maintenance_mode, max_upload_size, default_trial_days"
    )
    value = models.JSONField(verbose_name="Valeur")
    description = models.TextField(blank=True, verbose_name="Description")
    
    # Type pour validation
    value_type = models.CharField(
        max_length=20,
        choices=[
            ('string', 'Texte'),
            ('integer', 'Nombre entier'),
            ('float', 'Nombre decimal'),
            ('boolean', 'Booleen'),
            ('json', 'JSON'),
        ],
        default='string',
        verbose_name="Type"
    )
    
    # Audit
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Modifie par"
    )

    class Meta:
        verbose_name = "Configuration"
        verbose_name_plural = "Configurations"
        ordering = ['key']

    def __str__(self):
        return f"{self.key} = {self.value}"
    
    @classmethod
    def get(cls, key: str, default=None):
        """Recupere une valeur de configuration"""
        try:
            config = cls.objects.get(key=key)
            return config.value
        except cls.DoesNotExist:
            return default
    
    @classmethod
    def set(cls, key: str, value, user=None, description: str = ''):
        """Definit une valeur de configuration"""
        config, created = cls.objects.update_or_create(
            key=key,
            defaults={
                'value': value,
                'updated_by': user,
                'description': description or ''
            }
        )
        return config


class AuditLog(models.Model):
    """
    Journal d'audit des actions superadmin.
    Trace toutes les modifications importantes.
    """
    class Action(models.TextChoices):
        # Actions sur les owners
        OWNER_VIEWED = 'owner_viewed', 'Owner consulte'
        OWNER_SUSPENDED = 'owner_suspended', 'Owner suspendu'
        OWNER_ACTIVATED = 'owner_activated', 'Owner reactive'
        OWNER_PASSWORD_RESET = 'owner_password_reset', 'Mot de passe reinitialise'
        OWNER_IMPERSONATED = 'owner_impersonated', 'Session impersonnee'
        
        # Actions sur les subscriptions
        SUBSCRIPTION_VIEWED = 'subscription_viewed', 'Abonnement consulte'
        SUBSCRIPTION_EXTENDED = 'subscription_extended', 'Abonnement prolonge'
        SUBSCRIPTION_UPGRADED = 'subscription_upgraded', 'Abonnement upgrade'
        SUBSCRIPTION_CANCELLED = 'subscription_cancelled', 'Abonnement annule'
        
        # Actions sur les feature flags
        FLAG_CREATED = 'flag_created', 'Flag cree'
        FLAG_UPDATED = 'flag_updated', 'Flag modifie'
        FLAG_DELETED = 'flag_deleted', 'Flag supprime'
        FLAG_TOGGLED = 'flag_toggled', 'Flag (de)active'
        
        # Actions sur la configuration
        CONFIG_UPDATED = 'config_updated', 'Configuration modifiee'
        
        # Actions systeme
        SYSTEM_HEALTH_CHECK = 'system_health_check', 'Verification sante'
        BULK_ACTION = 'bulk_action', 'Action en masse'
    
    # Admin qui a effectue l'action
    admin = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        related_name='audit_logs',
        verbose_name="Administrateur"
    )
    
    # Action effectuee
    action = models.CharField(
        max_length=50,
        choices=Action.choices,
        verbose_name="Action"
    )
    
    # Cible de l'action (polymorphique)
    target_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    target_id = models.PositiveIntegerField(null=True, blank=True)
    target = GenericForeignKey('target_type', 'target_id')
    target_repr = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Representation cible",
        help_text="String representation au moment de l'action"
    )
    
    # Details de l'action
    details = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Details",
        help_text="Donnees avant/apres, parametres, etc."
    )
    
    # Contexte
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name="Adresse IP")
    user_agent = models.TextField(blank=True, verbose_name="User Agent")
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Date")

    class Meta:
        verbose_name = "Log d'audit"
        verbose_name_plural = "Logs d'audit"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['action']),
            models.Index(fields=['admin']),
            models.Index(fields=['created_at']),
            models.Index(fields=['target_type', 'target_id']),
        ]

    def __str__(self):
        admin_name = self.admin.email if self.admin else 'System'
        return f"{admin_name} - {self.get_action_display()} - {self.created_at}"
    
    @classmethod
    def log(cls, admin, action: str, target=None, details: dict = None, request=None):
        """
        Cree une entree de log.
        
        Args:
            admin: User qui effectue l'action
            action: Action (utiliser AuditLog.Action.XXX)
            target: Objet cible (Owner, Subscription, etc.)
            details: Dict de details supplementaires
            request: HttpRequest pour extraire IP et user agent
        """
        log_entry = cls(
            admin=admin,
            action=action,
            details=details or {}
        )
        
        if target:
            log_entry.target = target
            log_entry.target_repr = str(target)[:255]
        
        if request:
            log_entry.ip_address = cls._get_client_ip(request)
            log_entry.user_agent = request.META.get('HTTP_USER_AGENT', '')[:500]
        
        log_entry.save()
        return log_entry
    
    @staticmethod
    def _get_client_ip(request):
        """Extrait l'IP client de la requete"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR')


class DailyMetrics(models.Model):
    """
    Metriques journalieres agregees pour historique et graphiques.
    Une ligne par jour avec toutes les metriques cles.
    """
    date = models.DateField(unique=True, verbose_name="Date")
    
    # === Metriques Owners ===
    total_owners = models.PositiveIntegerField(default=0, verbose_name="Total owners")
    new_owners = models.PositiveIntegerField(default=0, verbose_name="Nouveaux owners")
    active_owners = models.PositiveIntegerField(
        default=0,
        verbose_name="Owners actifs",
        help_text="Owners connectes ce jour"
    )
    
    # === Metriques Subscriptions ===
    total_subscriptions = models.PositiveIntegerField(default=0, verbose_name="Total abonnements")
    trial_subscriptions = models.PositiveIntegerField(default=0, verbose_name="En essai")
    active_subscriptions = models.PositiveIntegerField(default=0, verbose_name="Abonnements actifs")
    churned_subscriptions = models.PositiveIntegerField(default=0, verbose_name="Churns du jour")
    
    # Par plan
    subscriptions_by_plan = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Abonnements par plan",
        help_text='{"free": 10, "pro": 5, "business": 2}'
    )
    
    # === Metriques Revenue (XOF) ===
    mrr = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name="MRR",
        help_text="Monthly Recurring Revenue"
    )
    arr = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        verbose_name="ARR",
        help_text="Annual Recurring Revenue"
    )
    new_mrr = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name="Nouveau MRR",
        help_text="MRR ajoute ce jour"
    )
    churned_mrr = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name="MRR perdu",
        help_text="MRR perdu par churn"
    )
    revenue_today = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name="Revenue du jour",
        help_text="Paiements recus ce jour"
    )
    
    # === Metriques Usage Platform ===
    total_leads = models.PositiveIntegerField(default=0, verbose_name="Total leads")
    new_leads = models.PositiveIntegerField(default=0, verbose_name="Nouveaux leads")
    total_widgets = models.PositiveIntegerField(default=0, verbose_name="Total widgets")
    active_widgets = models.PositiveIntegerField(default=0, verbose_name="Widgets actifs")
    total_sessions = models.PositiveIntegerField(default=0, verbose_name="Total sessions WiFi")
    new_sessions = models.PositiveIntegerField(default=0, verbose_name="Nouvelles sessions")
    active_sessions = models.PositiveIntegerField(default=0, verbose_name="Sessions actives")
    
    # === Metriques Techniques ===
    api_calls = models.PositiveIntegerField(default=0, verbose_name="Appels API")
    api_errors = models.PositiveIntegerField(default=0, verbose_name="Erreurs API")
    avg_response_time_ms = models.PositiveIntegerField(default=0, verbose_name="Temps reponse moyen (ms)")
    celery_tasks_completed = models.PositiveIntegerField(default=0, verbose_name="Taches Celery terminees")
    celery_tasks_failed = models.PositiveIntegerField(default=0, verbose_name="Taches Celery echouees")
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Metriques journalieres"
        verbose_name_plural = "Metriques journalieres"
        ordering = ['-date']

    def __str__(self):
        return f"Metriques {self.date}"
    
    @classmethod
    def get_or_create_today(cls):
        """Recupere ou cree les metriques du jour"""
        today = timezone.now().date()
        metrics, created = cls.objects.get_or_create(date=today)
        return metrics


class AlertRule(models.Model):
    """
    Regles d'alertes automatiques pour le superadmin.
    Notifie quand certains seuils sont atteints.
    """
    class Metric(models.TextChoices):
        CHURN_RATE = 'churn_rate', 'Taux de churn'
        ERROR_RATE = 'error_rate', 'Taux d\'erreurs API'
        NEW_SIGNUPS = 'new_signups', 'Nouvelles inscriptions'
        REVENUE_DROP = 'revenue_drop', 'Baisse de revenue'
        CELERY_FAILURES = 'celery_failures', 'Echecs Celery'
        ACTIVE_SESSIONS = 'active_sessions', 'Sessions actives'
    
    class Operator(models.TextChoices):
        GT = 'gt', 'Superieur a'
        LT = 'lt', 'Inferieur a'
        EQ = 'eq', 'Egal a'
        GTE = 'gte', 'Superieur ou egal a'
        LTE = 'lte', 'Inferieur ou egal a'
    
    name = models.CharField(max_length=200, verbose_name="Nom")
    metric = models.CharField(max_length=50, choices=Metric.choices, verbose_name="Metrique")
    operator = models.CharField(max_length=10, choices=Operator.choices, verbose_name="Operateur")
    threshold = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Seuil")
    
    # Notification
    notify_email = models.EmailField(blank=True, verbose_name="Email notification")
    notify_webhook = models.URLField(blank=True, verbose_name="Webhook URL")
    
    # Etat
    is_active = models.BooleanField(default=True, verbose_name="Active")
    last_triggered = models.DateTimeField(null=True, blank=True, verbose_name="Derniere alerte")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Regle d'alerte"
        verbose_name_plural = "Regles d'alerte"

    def __str__(self):
        return f"{self.name}: {self.get_metric_display()} {self.get_operator_display()} {self.threshold}"
    
    def check_condition(self, value) -> bool:
        """Verifie si la condition est remplie"""
        ops = {
            'gt': lambda v, t: v > t,
            'lt': lambda v, t: v < t,
            'eq': lambda v, t: v == t,
            'gte': lambda v, t: v >= t,
            'lte': lambda v, t: v <= t,
        }
        return ops[self.operator](Decimal(str(value)), self.threshold)
