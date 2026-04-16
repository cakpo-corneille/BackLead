from django.db import models
from django.conf import settings
from django.utils import timezone
from django.contrib.auth.models import (
    AbstractBaseUser,
    PermissionsMixin,
    BaseUserManager,
)


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email must be set")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True")
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_verify = models.BooleanField(default=False, help_text="Email vérifié par OTP")
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    def __str__(self):
        return self.email


class OwnerProfile(models.Model):
    MAIN_GOAL_CHOICES = [
        ("collect_leads", "Collecter des leads"),
        ("analytics", "Analyser le trafic"),
        ("marketing", "Marketing ciblé"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    business_name = models.CharField(max_length=255)
    logo = models.ImageField(
        upload_to="logos/profile", default="logos/profile/default.png", blank=True
    )
    nom = models.CharField(max_length=150, blank=True)
    prenom = models.CharField(max_length=150, blank=True)
    phone_contact = models.CharField(max_length=20, blank=True)
    whatsapp_contact = models.CharField(max_length=30, blank=True)
    pays = models.CharField(max_length=100, blank=True)
    ville = models.CharField(max_length=100, blank=True)
    quartier = models.CharField(max_length=100, blank=True)
    main_goal = models.CharField(max_length=50, choices=MAIN_GOAL_CHOICES, blank=True)
    pass_onboarding = models.BooleanField(default=False, editable=False)
    is_complete = models.BooleanField(default=False, editable=False)

    def __str__(self):
        return self.business_name

    def save(self, *args, **kwargs):
        """Calcul automatique de is_complete."""
        # Champs obligatoires
        required_checks = [
            bool(
                self.business_name and self.business_name != f"WIFI-ZONE {self.user.id}"
            ),  # Personnalisé
            bool(self.logo and self.logo.name != "logos/default.png"),  # Personnalisé
            bool(self.nom),
            bool(self.phone_contact or self.whatsapp_contact),
            bool(self.pays),
            bool(self.ville),
            bool(self.quartier),
            bool(self.main_goal),
        ]

        self.pass_onboarding = all(required_checks)
        self.is_complete = all(
            [
                self.pass_onboarding,
                bool(self.prenom),
                bool(self.phone_contact),
                bool(self.whatsapp_contact),
            ]
        )
        super().save(*args, **kwargs)
