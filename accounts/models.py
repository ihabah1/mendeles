from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra):
        if not email:
            raise ValueError('נדרש אימייל')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault('is_staff', True)
        extra.setdefault('is_superuser', True)
        extra.setdefault('is_active', True)
        extra.setdefault('role', User.Role.ADMIN)
        return self.create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    class Role(models.TextChoices):
        ADMIN = 'admin', 'מנהל'
        TEAM = 'team', 'חבר צוות'
        CUSTOMER = 'customer', 'לקוח'

    email = models.EmailField('אימייל', unique=True)
    username = models.CharField('שם משתמש', max_length=50, unique=True, blank=True, null=True)
    first_name = models.CharField('שם פרטי', max_length=60, blank=True)
    last_name = models.CharField('שם משפחה', max_length=60, blank=True)
    full_name = models.CharField('שם מלא', max_length=120, blank=True)
    phone = models.CharField('טלפון', max_length=20, blank=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CUSTOMER)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)
    last_login = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = 'משתמש'
        verbose_name_plural = 'משתמשים'

    def __str__(self):
        return self.email

    @property
    def display_name(self) -> str:
        """שם ידידותי (פרופיל, הודעות)."""
        if self.first_name and self.first_name.strip():
            return self.first_name.strip()
        if self.username and self.username.strip():
            return self.username.strip()
        if self.full_name and self.full_name.strip():
            return self.full_name.strip().split()[0]
        return self.email.split('@')[0]

    @property
    def nav_greeting_name(self) -> str:
        """שלום … בסרגל: admin למנהל, אחרת שם משתמש."""
        if self.is_admin:
            return 'admin'
        if self.username and self.username.strip():
            return self.username.strip()
        return self.email.split('@')[0]

    def sync_full_name(self) -> None:
        parts = [self.first_name.strip(), self.last_name.strip()]
        joined = ' '.join(p for p in parts if p)
        if joined:
            self.full_name = joined[:120]

    @property
    def is_admin(self):
        return self.email.lower() == settings.ADMIN_EMAIL.lower()

    @property
    def is_team_member(self):
        return self.role == self.Role.TEAM

    def get_role_display_badge(self):
        return dict(self.Role.choices).get(self.role, self.role)

    def get_initials(self):
        if self.full_name:
            parts = self.full_name.strip().split()
            if len(parts) >= 2:
                return (parts[0][0] + parts[-1][0]).upper()
            return parts[0][0].upper()
        return self.email[0].upper()
