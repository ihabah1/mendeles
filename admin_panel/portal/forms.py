from django import forms
from django.conf import settings

from admin_panel.accounts.auth_utils import authenticate_user
from admin_panel.accounts.models import User
from admin_panel.accounts.permissions import is_portal_admin
from admin_panel.portal.models import CustomerProfile, CreditAccount


class AdminLoginForm(forms.Form):
    email = forms.EmailField(
        label='אימייל',
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'admin@admin.com',
            'autocomplete': 'username',
            'dir': 'ltr',
        }),
    )
    password = forms.CharField(
        label='סיסמה',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': '••••••••',
            'autocomplete': 'current-password',
        }),
    )

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        self.user = None
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        email = cleaned.get('email')
        password = cleaned.get('password')
        if email and password:
            user, err = authenticate_user(email, password)
            if err:
                raise forms.ValidationError(err)
            if not is_portal_admin(user):
                raise forms.ValidationError('אין לך הרשאת גישה ללוח הניהול')
            self.user = user
        return cleaned


class UserCreateForm(forms.ModelForm):
    password = forms.CharField(
        label='סיסמה',
        min_length=4,
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
    )
    role = forms.ChoiceField(
        label='סוג משתמש',
        choices=[
            (User.Role.CUSTOMER, 'לקוח'),
            (User.Role.TEAM, 'חבר צוות'),
        ],
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    class Meta:
        model = User
        fields = ('email', 'full_name', 'phone', 'role')
        widgets = {
            'email': forms.EmailInput(attrs={'class': 'form-control', 'dir': 'ltr'}),
            'full_name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError('אימייל כבר קיים')
        if email == settings.ADMIN_EMAIL.lower():
            raise forms.ValidationError('לא ניתן ליצור משתמש מנהל ראשי')
        return email


class ProfileEditForm(forms.ModelForm):
    class Meta:
        model = CustomerProfile
        fields = ('id_number', 'city', 'address', 'status', 'subscription_type', 'notes')
        widgets = {
            'id_number': forms.TextInput(attrs={'class': 'form-control'}),
            'city': forms.TextInput(attrs={'class': 'form-control'}),
            'address': forms.TextInput(attrs={'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'subscription_type': forms.TextInput(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class CreditEditForm(forms.ModelForm):
    class Meta:
        model = CreditAccount
        fields = (
            'card_last4', 'card_brand', 'card_holder',
            'expiry_month', 'expiry_year',
            'balance_ils', 'total_topup_ils', 'total_charge_ils', 'is_verified',
        )
        widgets = {
            'card_last4': forms.TextInput(attrs={'class': 'form-control', 'maxlength': 4}),
            'card_brand': forms.TextInput(attrs={'class': 'form-control'}),
            'card_holder': forms.TextInput(attrs={'class': 'form-control'}),
            'expiry_month': forms.NumberInput(attrs={'class': 'form-control'}),
            'expiry_year': forms.NumberInput(attrs={'class': 'form-control'}),
            'balance_ils': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'total_topup_ils': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'total_charge_ils': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'is_verified': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class AIChangeRequestForm(forms.Form):
    prompt = forms.CharField(
        label='בקשת שינוי (שפה טבעית)',
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 6,
            'placeholder': 'לדוגמה: הגדל את גודל הפונט של כותרת ה-hero בדף הבית',
        }),
    )


class MessageForm(forms.Form):
    subject = forms.CharField(max_length=200, widget=forms.TextInput(attrs={'class': 'form-control'}))
    body = forms.CharField(widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 4}))
    channel = forms.ChoiceField(
        choices=[('sms', 'SMS'), ('email', 'אימייל'), ('push', 'התראה'), ('system', 'מערכת')],
        widget=forms.Select(attrs={'class': 'form-control'}),
    )
