from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import Category, Program, Team, Contestant, Participation, TeamPoints, User, Competition, SystemSetting

# Register other models
admin.site.register(Category)
admin.site.register(Program)
admin.site.register(Team)
admin.site.register(Contestant)
admin.site.register(Participation)
admin.site.register(TeamPoints)
admin.site.register(Competition)
admin.site.register(SystemSetting)
# Custom User admin
class UserAdmin(BaseUserAdmin):
    list_display = ('username', 'email', 'role', 'is_active')
    list_filter = ('role', 'is_superuser')

admin.site.register(User, UserAdmin)  # ✅ This is the correct registration
