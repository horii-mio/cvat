# Generated by Django 2.1.5 on 2019-02-05 19:56

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('engine', '0024_pluginoption'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='label',
            unique_together={('task', 'name')},
        ),
    ]
