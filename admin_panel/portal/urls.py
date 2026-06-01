from django.conf import settings
from django.urls import path

from . import ai_views, views

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
    path(f'{_prefix}/ai/jobs/', ai_views.ai_jobs_list, name='ai_jobs'),
    path(f'{_prefix}/ai/jobs/status/', ai_views.ai_queue_status, name='ai_queue_status'),
    path(f'{_prefix}/ai/jobs/<int:job_id>/cancel/', ai_views.ai_job_cancel, name='ai_job_cancel'),
    path(f'{_prefix}/ai/', ai_views.ai_requests_list, name='ai_requests'),
    path(f'{_prefix}/ai/repo-content/', ai_views.ai_repo_content, name='ai_repo_content'),
    path(f'{_prefix}/ai/<int:pk>/diag/', ai_views.ai_request_diag, name='ai_request_diag'),
    path(f'{_prefix}/ai/new/', ai_views.ai_request_create, name='ai_request_create'),
    path(f'{_prefix}/ai/<int:pk>/', ai_views.ai_request_detail, name='ai_request_detail'),
    path(f'{_prefix}/ai/<int:pk>/status/', ai_views.ai_request_status, name='ai_request_status'),
    path(f'{_prefix}/ai/<int:pk>/generate/', ai_views.ai_request_generate, name='ai_request_generate'),
    path(f'{_prefix}/ai/<int:pk>/approve/', ai_views.ai_request_approve, name='ai_request_approve'),
    path(f'{_prefix}/ai/<int:pk>/merge/', ai_views.ai_request_merge, name='ai_request_merge'),
    path(f'{_prefix}/ai/<int:pk>/reject/', ai_views.ai_request_reject, name='ai_request_reject'),
    path(f'{_prefix}/ai/<int:pk>/archive/', ai_views.ai_request_archive, name='ai_request_archive'),
    path(f'{_prefix}/ai/<int:pk>/cancel/', ai_views.ai_request_cancel, name='ai_request_cancel'),
    path(f'{_prefix}/ai/<int:pk>/retry/', ai_views.ai_request_retry, name='ai_request_retry'),
    path(
        f'{_prefix}/ai/<int:pk>/image/<path:filename>',
        ai_views.ai_request_image,
        name='ai_request_image',
    ),
]
