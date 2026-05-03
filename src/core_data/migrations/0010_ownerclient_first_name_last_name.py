from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core_data', '0009_ownerclient_user_agent'),
    ]

    operations = [
        migrations.AddField(
            model_name='ownerclient',
            name='first_name',
            field=models.CharField(blank=True, default='', max_length=150, help_text="Prénom extrait automatiquement du payload à l'ingestion."),
        ),
        migrations.AddField(
            model_name='ownerclient',
            name='last_name',
            field=models.CharField(blank=True, default='', max_length=150, help_text="Nom de famille extrait automatiquement du payload à l'ingestion."),
        ),
    ]
