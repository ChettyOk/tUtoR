from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('interactions', '0004_alter_notification_type'),
    ]

    operations = [
        migrations.AlterField(
            model_name='notification',
            name='type',
            field=models.CharField(
                choices=[
                    ('requested', 'Requested'),
                    ('interest', 'Tutoring request interest'),
                    ('confirmation', 'Confirmation'),
                    ('cancellation', 'Cancellation'),
                    ('rating', 'Rating'),
                ],
                default='requested',
                max_length=20,
            ),
        ),
    ]
