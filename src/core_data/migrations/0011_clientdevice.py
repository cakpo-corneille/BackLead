from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core_data', '0010_ownerclient_first_name_last_name'),
    ]

    operations = [
        migrations.CreateModel(
            name='ClientDevice',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('mac_address', models.CharField(db_index=True, max_length=17)),
                ('user_agent', models.CharField(blank=True, default='', max_length=512)),
                ('first_seen', models.DateTimeField(auto_now_add=True)),
                ('last_seen', models.DateTimeField(auto_now=True)),
                ('client', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='devices',
                    to='core_data.ownerclient'
                )),
            ],
            options={
                'verbose_name': 'Client Device',
                'verbose_name_plural': 'Client Devices',
                'ordering': ['-last_seen'],
                'unique_together': {('client', 'mac_address')},
            },
        ),
    ]
