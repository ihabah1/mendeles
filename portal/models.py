from django.conf import settings
from django.db import models


class CustomerProfile(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'active', 'פעיל'
        LOCKED = 'locked', 'נעול'
        PENDING = 'pending', 'ממתין'

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
    )
    id_number = models.CharField('ת.ז.', max_length=20, blank=True)
    city = models.CharField('עיר', max_length=80, blank=True)
    address = models.CharField('כתובת', max_length=200, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    notes = models.TextField('הערות פנימיות', blank=True)
    subscription_type = models.CharField('סוג מנוי', max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'פרופיל לקוח'
        verbose_name_plural = 'פרופילי לקוחות'

    def __str__(self):
        return self.user.full_name or self.user.email


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'ממתין'
        PAID = 'paid', 'שולם'
        PRINTING = 'printing', 'בדפוס'
        SHIPPED = 'shipped', 'נשלח'
        COMPLETED = 'completed', 'הושלם'
        CANCELLED = 'cancelled', 'בוטל'

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='orders',
    )
    order_number = models.CharField('מספר הזמנה', max_length=32, unique=True)
    draw_name = models.CharField('הגרלה', max_length=80, blank=True)
    forms_count = models.PositiveIntegerField('טפסים', default=1)
    amount_ils = models.DecimalField('סכום ₪', max_digits=10, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'הזמנה'
        verbose_name_plural = 'הזמנות'

    def __str__(self):
        return self.order_number


class CreditAccount(models.Model):
    customer = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='credit_account',
    )
    card_last4 = models.CharField('4 ספרות אחרונות', max_length=4, blank=True)
    card_brand = models.CharField('מותג כרטיס', max_length=30, blank=True)
    card_holder = models.CharField('שם בעל הכרטיס', max_length=120, blank=True)
    expiry_month = models.PositiveSmallIntegerField(null=True, blank=True)
    expiry_year = models.PositiveSmallIntegerField(null=True, blank=True)
    balance_ils = models.DecimalField('יתרה ₪', max_digits=10, decimal_places=2, default=0)
    total_topup_ils = models.DecimalField('סה"כ הפקדות', max_digits=12, decimal_places=2, default=0)
    total_charge_ils = models.DecimalField('סה"כ חיובים', max_digits=12, decimal_places=2, default=0)
    is_verified = models.BooleanField('מאומת', default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'חשבון אשראי'
        verbose_name_plural = 'חשבונות אשראי'

    def masked_card(self):
        if self.card_last4:
            return f'**** **** **** {self.card_last4}'
        return '—'


class CustomerMessage(models.Model):
    class Channel(models.TextChoices):
        SMS = 'sms', 'SMS'
        EMAIL = 'email', 'אימייל'
        PUSH = 'push', 'התראה'
        SYSTEM = 'system', 'מערכת'

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='messages',
    )
    channel = models.CharField(max_length=20, choices=Channel.choices, default=Channel.SYSTEM)
    subject = models.CharField('נושא', max_length=200)
    body = models.TextField('תוכן')
    sent_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ['-sent_at']
        verbose_name = 'הודעה'
        verbose_name_plural = 'הודעות'


class ActionLog(models.Model):
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='action_logs',
        null=True,
        blank=True,
    )
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='performed_actions',
    )
    event = models.CharField('אירוע', max_length=120)
    details = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'היסטוריית פעולות'
        verbose_name_plural = 'היסטוריות פעולות'


class CustomerPermission(models.Model):
    class Perm(models.TextChoices):
        PLACE_ORDER = 'place_order', 'ביצוע הזמנות'
        USE_WALLET = 'use_wallet', 'שימוש בארנק'
        VIEW_WINS = 'view_wins', 'צפייה בזכיות'
        SUBSCRIPTION = 'subscription', 'מנוי פעיל'
        PRINT_EXPORT = 'print_export', 'ייצוא להדפסה'

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='custom_permissions',
    )
    permission = models.CharField(max_length=40, choices=Perm.choices)
    is_granted = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='permission_updates',
    )

    class Meta:
        unique_together = [('customer', 'permission')]
        verbose_name = 'הרשאה'
        verbose_name_plural = 'הרשאות'
