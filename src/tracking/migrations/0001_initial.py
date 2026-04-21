import uuid
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('core_data', '0007_remove_conflictalert_is_resolved_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='TicketPlan',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('price_fcfa', models.PositiveIntegerField(help_text='Prix du ticket en FCFA')),
                ('duration_minutes', models.PositiveIntegerField(help_text='Durée de validité du ticket en minutes')),
                ('download_limit_mb', models.PositiveIntegerField(blank=True, help_text='Limite download en MB. Vide = illimité.', null=True)),
                ('upload_limit_mb', models.PositiveIntegerField(blank=True, help_text='Limite upload en MB. Vide = illimité.', null=True)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('owner', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='ticket_plans', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['owner', 'price_fcfa'],
            },
        ),
        migrations.AddIndex(
            model_name='ticketplan',
            index=models.Index(fields=['owner', 'is_active'], name='tracking_ti_owner_i_active_idx'),
        ),
        migrations.CreateModel(
            name='ConnectionSession',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('mac_address', models.CharField(db_index=True, max_length=17)),
                ('ip_address', models.GenericIPAddressField(blank=True, null=True)),
                ('ticket_id', models.CharField(blank=True, db_index=True, max_length=128, null=True)),
                ('mikrotik_session_id', models.CharField(blank=True, max_length=128, null=True)),
                ('session_key', models.UUIDField(db_index=True, default=uuid.uuid4, unique=True)),
                ('started_at', models.DateTimeField(auto_now_add=True)),
                ('ended_at', models.DateTimeField(blank=True, null=True)),
                ('last_heartbeat', models.DateTimeField(auto_now=True)),
                ('uptime_seconds', models.PositiveIntegerField(default=0)),
                ('bytes_downloaded', models.BigIntegerField(default=0)),
                ('bytes_uploaded', models.BigIntegerField(default=0)),
                ('download_limit_bytes', models.BigIntegerField(blank=True, null=True)),
                ('upload_limit_bytes', models.BigIntegerField(blank=True, null=True)),
                ('is_active', models.BooleanField(db_index=True, default=True)),
                ('last_raw_data', models.JSONField(blank=True, default=dict)),
                ('client', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='sessions', to='core_data.ownerclient')),
                ('owner', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tracking_sessions', to=settings.AUTH_USER_MODEL)),
                ('ticket_plan', models.ForeignKey(blank=True, help_text='Plan correspondant identifié automatiquement', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='sessions', to='tracking.ticketplan')),
            ],
            options={
                'ordering': ['-started_at'],
            },
        ),
        migrations.AddIndex(
            model_name='connectionsession',
            index=models.Index(fields=['owner', '-started_at'], name='tracking_co_owner_i_started_idx'),
        ),
        migrations.AddIndex(
            model_name='connectionsession',
            index=models.Index(fields=['owner', 'mac_address'], name='tracking_co_owner_i_mac_idx'),
        ),
        migrations.AddIndex(
            model_name='connectionsession',
            index=models.Index(fields=['owner', 'is_active'], name='tracking_co_owner_i_active_idx'),
        ),
    ]
