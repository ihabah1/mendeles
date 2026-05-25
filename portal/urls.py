from django.conf import settings
from django.urls import path

from . import views

app_name = 'portal'

_prefix = settings.ADMIN_DASHBOARD_PREFIX

urlpatterns = [
    path(f'{_prefix}/login/', views.admin_login, name='login'),
    path(f'{_prefix}/logout/', views.admin_logout, name='logout'),
    path(f'{_prefix}/', views.dashboard, name='dashboard'),
    path(f'{_prefix}', views.dashboard, name='dashboard-noslash'),
    path(f'{_prefix}/customers/', views.customers_list, name='customers'),
    path(f'{_prefix}/customers/new/', views.user_create, name='user_create'),
    path(f'{_prefix}/customers/<int:pk>/', views.customer_detail, name='customer_detail'),
    path(f'{_prefix}/customers/<int:pk>/delete/', views.user_delete, name='user_delete'),
    path(f'{_prefix}/customers/<int:pk>/team/', views.user_set_team, name='user_set_team'),
    path(f'{_prefix}/customers/<int:pk>/save-profile/', views.customer_save_profile, name='customer_save_profile'),
    path(f'{_prefix}/customers/<int:pk>/save-credit/', views.customer_save_credit, name='customer_save_credit'),
    path(f'{_prefix}/customers/<int:pk>/message/', views.send_message, name='send_message'),
    path(f'{_prefix}/customers/<int:pk>/permission/', views.toggle_permission, name='toggle_permission'),
    path(f'{_prefix}/customers/<int:pk>/permissions/grant-all/', views.permissions_grant_all, name='permissions_grant_all'),
    path(f'{_prefix}/customers/<int:pk>/permissions/revoke-all/', views.permissions_revoke_all, name='permissions_revoke_all'),
    path(f'{_prefix}/orders/', views.orders_list, name='orders'),
    path(f'{_prefix}/logs/', views.activity_logs, name='logs'),
    path(f'{_prefix}/api/stats/', views.api_stats, name='api_stats'),
]
