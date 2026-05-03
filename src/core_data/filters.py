import django_filters
from django.db import models
from .models import OwnerClient

class LeadFilter(django_filters.FilterSet):
    """
    Filtres avancés pour les leads collectés.
    Permet de filtrer par date (plage), statut de vérification, etc.
    """
    created_at_after = django_filters.DateTimeFilter(field_name="created_at", lookup_expr='gte')
    created_at_before = django_filters.DateTimeFilter(field_name="created_at", lookup_expr='lte')
    
    # Filtres booléens intelligents
    has_email = django_filters.BooleanFilter(field_name='email', method='filter_has_email')
    has_phone = django_filters.BooleanFilter(field_name='phone', method='filter_has_phone')
    
    class Meta:
        model = OwnerClient
        fields = ['is_verified', 'email', 'phone', 'created_at_after', 'created_at_before']

    def filter_has_email(self, queryset, name, value):
        if value is True:
            return queryset.exclude(email__isnull=True).exclude(email='')
        elif value is False:
            return queryset.filter(models.Q(email__isnull=True) | models.Q(email=''))
        return queryset

    def filter_has_phone(self, queryset, name, value):
        if value is True:
            return queryset.exclude(phone__isnull=True).exclude(phone='')
        elif value is False:
            return queryset.filter(models.Q(phone__isnull=True) | models.Q(phone=''))
        return queryset
