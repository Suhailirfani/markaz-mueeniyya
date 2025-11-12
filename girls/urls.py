# competition_app/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('', views.girls_page, name='girls_page'),
    path('dashboard_off_campus/', views.dashboard_off_campus, name='dashboard_off_campus'),
    path('add-category-off/', views.add_category_off, name='add_category_off'),
    path('add-program-off/', views.add_program_off, name='add_program_off'),
    
    
]