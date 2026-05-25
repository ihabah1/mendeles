from django.contrib import admin

from .models import (
    ActionLog,
    CreditAccount,
    CustomerMessage,
    CustomerPermission,
    CustomerProfile,
    Order,
)


@admin.register(CustomerProfile)
class CustomerProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'status', 'city', 'created_at')
    search_fields = ('user__email', 'user__full_name', 'user__phone')


admin.site.register(Order)
admin.site.register(CreditAccount)
admin.site.register(CustomerMessage)
admin.site.register(ActionLog)
admin.site.register(CustomerPermission)
