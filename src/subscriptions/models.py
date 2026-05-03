import uuid
from decimal import Decimal
from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator
from dateutil.relativedelta import relativedelta


class Plan(models.Model):
    """
    Plans d'abonnement disponibles (Free, Pro, Business, etc.)
    """
    name = models.CharField(max_length=100, verbose_name="Nom du plan")
    slug = models.SlugField(unique=True, verbose_name="Identifiant unique")
    description = models.TextField(blank=True, verbose_name="Description")
    
    # Tarification en XOF (Franc CFA)
    price_monthly = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))],
        verbose_name="Prix mensuel (XOF)"
    )
    price_yearly = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))],
        verbose_name="Prix annuel (XOF)"
    )
    currency = models.CharField(max_length=3, default='XOF', verbose_name="Devise")
    
    # Limites du plan
    max_widgets = models.PositiveIntegerField(default=1, verbose_name="Widgets max")
    max_leads_per_month = models.PositiveIntegerField(default=100, verbose_name="Leads/mois max")
    max_routers = models.PositiveIntegerField(default=1, verbose_name="Routeurs max")
    
    # Features du plan (JSON flexible)
    features = models.JSONField(
        default=dict,
        verbose_name="Fonctionnalites",
        help_text='Ex: {"analytics": true, "export_csv": true, "api_access": false, "priority_support": false}'
    )
    
    # Periode d'essai
    trial_days = models.PositiveIntegerField(default=14, verbose_name="Jours d'essai")
    
    # Etat et ordre
    is_active = models.BooleanField(default=True, verbose_name="Actif")
    is_popular = models.BooleanField(default=False, verbose_name="Populaire (mise en avant)")
    display_order = models.PositiveIntegerField(default=0, verbose_name="Ordre d'affichage")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Plan"
        verbose_name_plural = "Plans"
        ordering = ['display_order', 'price_monthly']

    def __str__(self):
        return f"{self.name} - {self.price_monthly} {self.currency}/mois"
    
    def get_price(self, billing_cycle: str) -> Decimal:
        """Retourne le prix selon le cycle de facturation"""
        if billing_cycle == 'yearly':
            return self.price_yearly
        return self.price_monthly
    
    def has_feature(self, feature_key: str) -> bool:
        """Verifie si le plan inclut une fonctionnalite"""
        return self.features.get(feature_key, False)


class Subscription(models.Model):
    """
    Abonnement d'un Owner a un Plan
    """
    class Status(models.TextChoices):
        TRIAL = 'trial', 'Essai gratuit'
        ACTIVE = 'active', 'Actif'
        PAST_DUE = 'past_due', 'Paiement en retard'
        CANCELLED = 'cancelled', 'Annule'
        EXPIRED = 'expired', 'Expire'
    
    class BillingCycle(models.TextChoices):
        MONTHLY = 'monthly', 'Mensuel'
        YEARLY = 'yearly', 'Annuel'
    
    # Relations
    owner = models.OneToOneField(
        'accounts.Owner',
        on_delete=models.CASCADE,
        related_name='subscription',
        verbose_name="Proprietaire"
    )
    plan = models.ForeignKey(
        Plan,
        on_delete=models.PROTECT,
        related_name='subscriptions',
        verbose_name="Plan"
    )
    
    # Statut et cycle
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.TRIAL,
        verbose_name="Statut"
    )
    billing_cycle = models.CharField(
        max_length=20,
        choices=BillingCycle.choices,
        default=BillingCycle.MONTHLY,
        verbose_name="Cycle de facturation"
    )
    
    # Dates de periode d'essai
    trial_start = models.DateTimeField(null=True, blank=True, verbose_name="Debut essai")
    trial_end = models.DateTimeField(null=True, blank=True, verbose_name="Fin essai")
    
    # Dates de la periode courante
    current_period_start = models.DateTimeField(verbose_name="Debut periode")
    current_period_end = models.DateTimeField(verbose_name="Fin periode")
    
    # Annulation
    cancelled_at = models.DateTimeField(null=True, blank=True, verbose_name="Annule le")
    cancel_reason = models.TextField(blank=True, verbose_name="Raison annulation")
    
    # Usage de la periode courante (reset a chaque renouvellement)
    leads_used = models.PositiveIntegerField(default=0, verbose_name="Leads utilises")
    
    # Metadata
    metadata = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Abonnement"
        verbose_name_plural = "Abonnements"
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['current_period_end']),
        ]

    def __str__(self):
        return f"{self.owner} - {self.plan.name} ({self.status})"
    
    def save(self, *args, **kwargs):
        # Initialiser les dates si nouvelle subscription
        if not self.pk:
            now = timezone.now()
            if self.status == self.Status.TRIAL and self.plan.trial_days > 0:
                self.trial_start = now
                self.trial_end = now + timezone.timedelta(days=self.plan.trial_days)
                self.current_period_start = now
                self.current_period_end = self.trial_end
            else:
                self.current_period_start = now
                self.current_period_end = self._calculate_period_end(now)
        super().save(*args, **kwargs)
    
    def _calculate_period_end(self, start_date) -> timezone.datetime:
        """Calcule la fin de periode selon le cycle"""
        if self.billing_cycle == self.BillingCycle.YEARLY:
            return start_date + relativedelta(years=1)
        return start_date + relativedelta(months=1)
    
    # === Methodes de verification des limites ===
    
    def can_create_lead(self) -> bool:
        """Verifie si l'owner peut creer un nouveau lead"""
        if self.status not in [self.Status.TRIAL, self.Status.ACTIVE]:
            return False
        return self.leads_used < self.plan.max_leads_per_month
    
    def can_create_widget(self, current_count: int) -> bool:
        """Verifie si l'owner peut creer un nouveau widget"""
        if self.status not in [self.Status.TRIAL, self.Status.ACTIVE]:
            return False
        return current_count < self.plan.max_widgets
    
    def can_create_router(self, current_count: int) -> bool:
        """Verifie si l'owner peut ajouter un nouveau routeur"""
        if self.status not in [self.Status.TRIAL, self.Status.ACTIVE]:
            return False
        return current_count < self.plan.max_routers
    
    def has_feature(self, feature_key: str) -> bool:
        """Verifie si l'abonnement donne acces a une fonctionnalite"""
        if self.status not in [self.Status.TRIAL, self.Status.ACTIVE]:
            return False
        return self.plan.has_feature(feature_key)
    
    def increment_lead_usage(self):
        """Incremente le compteur de leads utilises"""
        self.leads_used += 1
        self.save(update_fields=['leads_used', 'updated_at'])
    
    def reset_usage(self):
        """Reset les compteurs d'usage (appele au renouvellement)"""
        self.leads_used = 0
        self.save(update_fields=['leads_used', 'updated_at'])
    
    # === Methodes de gestion du cycle de vie ===
    
    def is_trial_expired(self) -> bool:
        """Verifie si la periode d'essai est expiree"""
        if self.status != self.Status.TRIAL:
            return False
        return self.trial_end and timezone.now() > self.trial_end
    
    def is_period_expired(self) -> bool:
        """Verifie si la periode courante est expiree"""
        return timezone.now() > self.current_period_end
    
    def days_until_renewal(self) -> int:
        """Nombre de jours avant le renouvellement"""
        delta = self.current_period_end - timezone.now()
        return max(0, delta.days)
    
    def renew(self):
        """Renouvelle l'abonnement pour une nouvelle periode"""
        now = timezone.now()
        self.current_period_start = now
        self.current_period_end = self._calculate_period_end(now)
        self.reset_usage()
        self.save()
    
    def cancel(self, reason: str = ''):
        """Annule l'abonnement (reste actif jusqu'a la fin de la periode)"""
        self.cancelled_at = timezone.now()
        self.cancel_reason = reason
        self.status = self.Status.CANCELLED
        self.save()
    
    def suspend(self):
        """Suspend l'abonnement pour non-paiement"""
        self.status = self.Status.PAST_DUE
        self.save()
    
    def activate(self):
        """Active l'abonnement apres paiement"""
        self.status = self.Status.ACTIVE
        self.save()
    
    def expire(self):
        """Expire l'abonnement"""
        self.status = self.Status.EXPIRED
        self.save()
    
    def get_current_price(self) -> Decimal:
        """Retourne le prix actuel de l'abonnement"""
        return self.plan.get_price(self.billing_cycle)


class Payment(models.Model):
    """
    Historique des paiements Mobile Money
    """
    class Status(models.TextChoices):
        PENDING = 'pending', 'En attente'
        PROCESSING = 'processing', 'En cours'
        COMPLETED = 'completed', 'Complete'
        FAILED = 'failed', 'Echoue'
        REFUNDED = 'refunded', 'Rembourse'
        CANCELLED = 'cancelled', 'Annule'
    
    class Provider(models.TextChoices):
        MTN_MOMO = 'mtn_momo', 'MTN Mobile Money'
        MOOV_MONEY = 'moov_money', 'Moov Money'
        MANUAL = 'manual', 'Manuel (Admin)'
    
    # Identifiant unique
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    
    # Relations
    subscription = models.ForeignKey(
        Subscription,
        on_delete=models.CASCADE,
        related_name='payments',
        verbose_name="Abonnement"
    )
    
    # Montant
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        verbose_name="Montant"
    )
    currency = models.CharField(max_length=3, default='XOF', verbose_name="Devise")
    
    # Statut et provider
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name="Statut"
    )
    provider = models.CharField(
        max_length=20,
        choices=Provider.choices,
        verbose_name="Moyen de paiement"
    )
    
    # Informations Mobile Money
    phone_number = models.CharField(max_length=20, verbose_name="Numero telephone")
    external_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="ID transaction externe"
    )
    external_reference = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="Reference externe"
    )
    
    # Description
    description = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Description"
    )
    
    # Metadata (reponse API, details erreur, etc.)
    metadata = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True, verbose_name="Message d'erreur")
    
    # Dates
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name="Complete le")

    class Meta:
        verbose_name = "Paiement"
        verbose_name_plural = "Paiements"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['external_id']),
            models.Index(fields=['phone_number']),
        ]

    def __str__(self):
        return f"{self.amount} {self.currency} - {self.provider} ({self.status})"
    
    def mark_completed(self, external_id: str = None):
        """Marque le paiement comme complete"""
        self.status = self.Status.COMPLETED
        self.completed_at = timezone.now()
        if external_id:
            self.external_id = external_id
        self.save()
    
    def mark_failed(self, error_message: str = ''):
        """Marque le paiement comme echoue"""
        self.status = self.Status.FAILED
        self.error_message = error_message
        self.save()
    
    def mark_processing(self, external_id: str = None):
        """Marque le paiement comme en cours de traitement"""
        self.status = self.Status.PROCESSING
        if external_id:
            self.external_id = external_id
        self.save()


class Invoice(models.Model):
    """
    Factures generees pour les abonnements
    """
    # Relations
    subscription = models.ForeignKey(
        Subscription,
        on_delete=models.CASCADE,
        related_name='invoices',
        verbose_name="Abonnement"
    )
    payment = models.OneToOneField(
        Payment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invoice',
        verbose_name="Paiement associe"
    )
    
    # Numero de facture unique
    invoice_number = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="Numero de facture"
    )
    
    # Montant
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="Montant"
    )
    currency = models.CharField(max_length=3, default='XOF', verbose_name="Devise")
    
    # Periode couverte
    period_start = models.DateTimeField(verbose_name="Debut periode")
    period_end = models.DateTimeField(verbose_name="Fin periode")
    
    # Etat
    is_paid = models.BooleanField(default=False, verbose_name="Payee")
    paid_at = models.DateTimeField(null=True, blank=True, verbose_name="Payee le")
    
    # Document
    pdf_url = models.URLField(null=True, blank=True, verbose_name="URL PDF")
    
    # Informations de facturation (snapshot au moment de la creation)
    billing_info = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Informations de facturation",
        help_text="Snapshot des infos owner au moment de la facture"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Facture"
        verbose_name_plural = "Factures"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.invoice_number} - {self.amount} {self.currency}"
    
    def save(self, *args, **kwargs):
        # Generer le numero de facture si nouveau
        if not self.invoice_number:
            self.invoice_number = self._generate_invoice_number()
        super().save(*args, **kwargs)
    
    def _generate_invoice_number(self) -> str:
        """Genere un numero de facture unique: WFL-YYYY-NNNN"""
        year = timezone.now().year
        last_invoice = Invoice.objects.filter(
            invoice_number__startswith=f'WFL-{year}-'
        ).order_by('-invoice_number').first()
        
        if last_invoice:
            last_num = int(last_invoice.invoice_number.split('-')[-1])
            new_num = last_num + 1
        else:
            new_num = 1
        
        return f'WFL-{year}-{new_num:04d}'
    
    def mark_paid(self, payment: Payment = None):
        """Marque la facture comme payee"""
        self.is_paid = True
        self.paid_at = timezone.now()
        if payment:
            self.payment = payment
        self.save()
