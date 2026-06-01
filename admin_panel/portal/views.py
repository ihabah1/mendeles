from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.views.decorators.cache import never_cache
from django.db.models import Count, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from admin_panel.accounts.models import User
from admin_panel.accounts.permissions import is_portal_admin
from admin_panel.portal.decorators import admin_required
from admin_panel.portal.forms import (
    AdminLoginForm,
    CreditEditForm,
    MessageForm,
    ProfileEditForm,
    UserCreateForm,
)
from admin_panel.portal.models import (
    ActionLog,
    CreditAccount,
    CustomerMessage,
    CustomerPermission,
    CustomerProfile,
    Order,
)


def _client_ip(request):
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def _log_action(request, event, customer=None, details=''):
    ActionLog.objects.create(
        customer=customer,
        performed_by=request.user,
        event=event,
        details=details,
        ip_address=_client_ip(request),
    )


def _managed_users_queryset():
    return User.objects.exclude(
        email__iexact=settings.ADMIN_EMAIL,
    ).filter(role__in=[User.Role.CUSTOMER, User.Role.TEAM])


def _get_managed_user(pk):
    return get_object_or_404(_managed_users_queryset(), pk=pk)


def _ensure_profile_and_credit(user):
    profile, _ = CustomerProfile.objects.get_or_create(user=user)
    credit, _ = CreditAccount.objects.get_or_create(customer=user)
    return profile, credit


@never_cache
def admin_login(request):
    if is_portal_admin(request.user):
        next_url = request.GET.get('next') or ''
        if next_url.startswith('/manage'):
            return redirect(next_url)
        return redirect('portal:customers')

    form = AdminLoginForm(request)
    if request.method == 'POST':
        form = AdminLoginForm(request, request.POST)
        if form.is_valid():
            user = form.user
            login(request, user)
            _log_action(request, 'admin.login', details=user.email)
            next_url = request.GET.get('next') or request.POST.get('next')
            if next_url and next_url.startswith('/manage'):
                return redirect(next_url)
            return redirect('portal:customers')

    return render(request, 'portal/login.html', {'form': form})


@admin_required
def admin_logout(request):
    _log_action(request, 'admin.logout')
    logout(request)
    return redirect('portal:login')


@admin_required
def dashboard(request):
    if is_portal_admin(request.user):
        return redirect('portal:customers')
    return redirect('portal:login')


@admin_required
def customers_list(request):
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    role_filter = request.GET.get('role', '')

    users = _managed_users_queryset().select_related('profile')
    if q:
        users = users.filter(
            Q(full_name__icontains=q) | Q(email__icontains=q) | Q(phone__icontains=q),
        )
    if status:
        users = users.filter(profile__status=status)
    if role_filter in (User.Role.CUSTOMER, User.Role.TEAM):
        users = users.filter(role=role_filter)

    users = users.annotate(orders_count=Count('orders')).order_by('-date_joined')

    return render(request, 'portal/customers.html', {
        'customers': users,
        'q': q,
        'status': status,
        'role_filter': role_filter,
    })


@admin_required
def user_create(request):
    form = UserCreateForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save(commit=False)
        user.set_password(form.cleaned_data['password'])
        user.is_active = True
        user.save()
        _ensure_profile_and_credit(user)
        for perm, _ in CustomerPermission.Perm.choices:
            CustomerPermission.objects.create(
                customer=user,
                permission=perm,
                is_granted=True,
                updated_by=request.user,
            )
        _log_action(request, 'user.created', customer=user, details=user.email)
        messages.success(request, f'משתמש {user.email} נוצר בהצלחה')
        return redirect('portal:customer_detail', pk=user.pk)

    return render(request, 'portal/user_form.html', {
        'form': form,
        'title': 'הוספת משתמש חדש',
    })


@admin_required
@require_POST
def user_delete(request, pk):
    user = _get_managed_user(pk)
    email = user.email
    user.delete()
    _log_action(request, 'user.deleted', details=email)
    messages.success(request, f'משתמש {email} נמחק')
    return redirect('portal:customers')


@admin_required
@require_POST
def user_set_team(request, pk):
    user = _get_managed_user(pk)
    if user.role == User.Role.TEAM:
        user.role = User.Role.CUSTOMER
        _log_action(request, 'user.team_removed', customer=user)
        messages.success(request, 'הוסר מתפקיד חבר צוות')
    else:
        user.role = User.Role.TEAM
        _log_action(request, 'user.team_set', customer=user)
        messages.success(request, 'הוגדר כחבר צוות')
    user.save()
    return redirect('portal:customer_detail', pk=pk)


@admin_required
def customer_detail(request, pk):
    customer = _get_managed_user(pk)
    profile, credit = _ensure_profile_and_credit(customer)
    orders = customer.orders.all()[:50]
    messages_list = customer.messages.all()[:50]
    logs = customer.action_logs.all()[:50]
    all_perms = CustomerPermission.Perm.choices
    granted = {
        p.permission for p in customer.custom_permissions.all() if p.is_granted
    }
    perm_rows = [
        {'key': k, 'label': lbl, 'granted': k in granted}
        for k, lbl in all_perms
    ]
    tab = request.GET.get('tab', 'profile')

    profile_form = ProfileEditForm(instance=profile)
    credit_form = CreditEditForm(instance=credit)
    message_form = MessageForm()

    return render(request, 'portal/customer_detail.html', {
        'customer': customer,
        'profile': profile,
        'credit': credit,
        'orders': orders,
        'messages_list': messages_list,
        'logs': logs,
        'perm_rows': perm_rows,
        'message_form': message_form,
        'profile_form': profile_form,
        'credit_form': credit_form,
        'tab': tab,
    })


@admin_required
@require_POST
def customer_save_profile(request, pk):
    from django.urls import reverse
    customer = _get_managed_user(pk)
    profile, _ = _ensure_profile_and_credit(customer)
    form = ProfileEditForm(request.POST, instance=profile)
    if form.is_valid():
        form.save()
        customer.full_name = request.POST.get('full_name', customer.full_name)
        customer.phone = request.POST.get('phone', customer.phone)
        customer.is_active = request.POST.get('is_active') == 'on'
        customer.save()
        _log_action(request, 'profile.updated', customer=customer)
        messages.success(request, 'פרופיל עודכן')
    else:
        messages.error(request, 'שגיאה בעדכון פרופיל')
    return redirect(reverse('portal:customer_detail', kwargs={'pk': pk}) + '?tab=profile')


@admin_required
@require_POST
def customer_save_credit(request, pk):
    from django.urls import reverse
    customer = _get_managed_user(pk)
    _, credit = _ensure_profile_and_credit(customer)
    form = CreditEditForm(request.POST, instance=credit)
    if form.is_valid():
        form.save()
        _log_action(request, 'credit.updated', customer=customer)
        messages.success(request, 'פרטי אשראי עודכנו')
    else:
        messages.error(request, 'שגיאה בעדכון אשראי')
    return redirect(reverse('portal:customer_detail', kwargs={'pk': pk}) + '?tab=credit')


@admin_required
@require_POST
def send_message(request, pk):
    from django.urls import reverse
    customer = _get_managed_user(pk)
    form = MessageForm(request.POST)
    if form.is_valid():
        CustomerMessage.objects.create(
            customer=customer,
            channel=form.cleaned_data['channel'],
            subject=form.cleaned_data['subject'],
            body=form.cleaned_data['body'],
        )
        _log_action(request, 'message.sent', customer=customer, details=form.cleaned_data['subject'])
        messages.success(request, 'הודעה נשלחה לתא הדואר של הלקוח')
    return redirect(reverse('portal:customer_detail', kwargs={'pk': pk}) + '?tab=messages')


@admin_required
@require_POST
def toggle_permission(request, pk):
    from django.urls import reverse
    customer = _get_managed_user(pk)
    perm = request.POST.get('permission')
    if perm in dict(CustomerPermission.Perm.choices):
        obj, created = CustomerPermission.objects.get_or_create(
            customer=customer,
            permission=perm,
            defaults={'updated_by': request.user, 'is_granted': True},
        )
        if not created:
            obj.is_granted = not obj.is_granted
            obj.updated_by = request.user
            obj.save()
        _log_action(request, 'permission.toggled', customer=customer, details=perm)
    return redirect(reverse('portal:customer_detail', kwargs={'pk': pk}) + '?tab=permissions')


@admin_required
@require_POST
def permissions_grant_all(request, pk):
    from django.urls import reverse
    customer = _get_managed_user(pk)
    for perm, _ in CustomerPermission.Perm.choices:
        CustomerPermission.objects.update_or_create(
            customer=customer,
            permission=perm,
            defaults={'is_granted': True, 'updated_by': request.user},
        )
    _log_action(request, 'permissions.grant_all', customer=customer)
    messages.success(request, 'כל ההרשאות הופעלו')
    return redirect(reverse('portal:customer_detail', kwargs={'pk': pk}) + '?tab=permissions')


@admin_required
@require_POST
def permissions_revoke_all(request, pk):
    from django.urls import reverse
    customer = _get_managed_user(pk)
    CustomerPermission.objects.filter(customer=customer).update(is_granted=False)
    _log_action(request, 'permissions.revoke_all', customer=customer)
    messages.success(request, 'כל ההרשאות בוטלו')
    return redirect(reverse('portal:customer_detail', kwargs={'pk': pk}) + '?tab=permissions')


@admin_required
def orders_list(request):
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    orders = Order.objects.select_related('customer').all()
    if q:
        orders = orders.filter(
            Q(order_number__icontains=q)
            | Q(customer__full_name__icontains=q)
            | Q(customer__email__icontains=q),
        )
    if status:
        orders = orders.filter(status=status)
    return render(request, 'portal/orders.html', {'orders': orders, 'q': q, 'status': status})


@admin_required
def activity_logs(request):
    logs = ActionLog.objects.select_related('customer', 'performed_by')[:200]
    return render(request, 'portal/logs.html', {'logs': logs})


@admin_required
@require_GET
def api_stats(request):
    orders = Order.objects.all()
    return JsonResponse({
        'users': _managed_users_queryset().count(),
        'orders': orders.count(),
        'pending': orders.filter(status=Order.Status.PENDING).count(),
        'revenue': str(orders.aggregate(t=Sum('amount_ils'))['t'] or 0),
        'time': timezone.localtime().isoformat(),
    })
