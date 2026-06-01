"""משתמשי דמו ב-Django (מקביל ל-create_demo_user.py ב-Flask)."""
from django.core.management.base import BaseCommand

from admin_panel.accounts.bootstrap import ensure_bootstrap_admin
from admin_panel.accounts.models import User
from admin_panel.portal.models import CreditAccount, CustomerProfile


class Command(BaseCommand):
    help = 'יוצר admin@admin.com ו-demo@mandeles.co.il ב-Django'

    def handle(self, *args, **options):
        ensure_bootstrap_admin()
        self.stdout.write(self.style.SUCCESS('admin@admin.com מוכן'))

        email = 'demo@mandeles.co.il'
        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                'first_name': 'דמו',
                'last_name': 'Mandeles',
                'role': User.Role.CUSTOMER,
            },
        )
        if created:
            user.set_password('demo1234')
            user.save()
        CustomerProfile.objects.get_or_create(user=user)
        credit, _ = CreditAccount.objects.get_or_create(customer=user)
        if credit.balance_ils < 500:
            credit.balance_ils = 500
            credit.save(update_fields=['balance_ils'])
        self.stdout.write(self.style.SUCCESS(f'{email} / demo1234 (יתרה ₪500)'))
