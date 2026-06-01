"""
Creates admin user, demo customers, orders, messages, permissions.
Usage: python manage.py setup_portal
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from admin_panel.accounts.bootstrap import BOOTSTRAP_ADMIN_EMAIL, ensure_bootstrap_admin
from admin_panel.accounts.models import User
from admin_panel.portal.models import (
    ActionLog,
    CreditAccount,
    CustomerMessage,
    CustomerPermission,
    CustomerProfile,
    Order,
)


class Command(BaseCommand):
    help = 'יוצר משתמש admin ונתוני דמו'

    @transaction.atomic
    def handle(self, *args, **options):
        admin, created = ensure_bootstrap_admin()
        self.stdout.write(self.style.SUCCESS(
            f'Admin: {BOOTSTRAP_ADMIN_EMAIL} / admin · active={admin.is_active} '
            f'({ "created" if created else "verified" })',
        ))

        demos = [
            ('יוסי כהן', 'yossi@demo.com', '0501111111', 'תל אביב'),
            ('מירי לוי', 'miri@demo.com', '0502222222', 'חיפה'),
            ('דוד אברהם', 'david@demo.com', '0503333333', 'ירושלים'),
        ]
        for i, (name, email, phone, city) in enumerate(demos, 1):
            user, u_created = User.objects.get_or_create(
                email=email,
                defaults={'full_name': name, 'phone': phone, 'role': User.Role.CUSTOMER},
            )
            if u_created:
                user.set_password('demo1234')
                user.save()
            profile, _ = CustomerProfile.objects.get_or_create(
                user=user,
                defaults={'city': city, 'status': CustomerProfile.Status.ACTIVE},
            )
            credit, _ = CreditAccount.objects.get_or_create(
                customer=user,
                defaults={
                    'card_last4': f'123{i}',
                    'card_brand': 'Visa',
                    'card_holder': name,
                    'expiry_month': 12,
                    'expiry_year': 2028,
                    'balance_ils': Decimal('150.00') * i,
                    'total_topup_ils': Decimal('500.00') * i,
                    'total_charge_ils': Decimal('350.00') * i,
                    'is_verified': True,
                },
            )
            for perm, _ in CustomerPermission.Perm.choices:
                CustomerPermission.objects.get_or_create(
                    customer=user,
                    permission=perm,
                    defaults={'is_granted': True, 'updated_by': admin},
                )
            statuses = [
                Order.Status.COMPLETED,
                Order.Status.PAID,
                Order.Status.PENDING,
            ]
            for j, st in enumerate(statuses):
                Order.objects.get_or_create(
                    order_number=f'ORD-{i:02d}-{j+1}',
                    defaults={
                        'customer': user,
                        'draw_name': f'לוטו 2026-{j+1}',
                        'forms_count': j + 2,
                        'amount_ils': Decimal('25.00') * (j + 1),
                        'status': st,
                    },
                )
            CustomerMessage.objects.get_or_create(
                customer=user,
                subject='ברוכים הבאים',
                defaults={
                    'channel': CustomerMessage.Channel.SYSTEM,
                    'body': f'שלום {name}, החשבון שלך הופעל בהצלחה.',
                },
            )
            ActionLog.objects.get_or_create(
                customer=user,
                event='customer.registered',
                defaults={'details': email, 'performed_by': admin},
            )

        self.stdout.write(self.style.SUCCESS('Demo data loaded successfully.'))
