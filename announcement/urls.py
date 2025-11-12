# competition_app/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('manage-announcements/', views.manage_announcements, name='manage_announcements'),
    path('toggle-announcement/<int:program_id>/', views.toggle_program_announcement, name='toggle_announcement'),
    path('bulk-announce/', views.bulk_announce_programs, name='bulk_announce_programs'),

    # Public URLs
    path('public-results/', views.public_results_home, name='public_results_home'),
    path('results/program/<int:program_id>/', views.public_program_result, name='public_program_result'),
    path('results/leaderboard/', views.public_leaderboard, name='public_leaderboard'),
]
