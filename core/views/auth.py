import os
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.views.decorators.cache import cache_control
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Q
from django.core.paginator import Paginator
from django.urls import reverse
from ..models import Program, Team, Contestant, SystemSetting

User = get_user_model()

def is_admin(user):
    return user.is_superuser or user.role == 'admin'

def landing_view(request):
    return render(request, 'landing.html')

@login_required
@user_passes_test(is_admin)
def lock_user(request, user_id):
    user = get_object_or_404(User, id=user_id)
    if user.role == 'team':
        user.is_active = False
        user.save()
    return redirect('view_users')

@login_required
@user_passes_test(is_admin)
def unlock_user(request, user_id):
    user = get_object_or_404(User, id=user_id)
    if user.role == 'team':
        user.is_active = True
        user.save()
    return redirect('view_users')

def custom_login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)

        if user is not None:
            if not user.is_approved:
                messages.error(request, 'Account pending approval by admin.')
                return redirect('login')

            if user.role == 'team' and not hasattr(user, 'team'):
                messages.error(request, 'Your account is approved, but you are not assigned to a team yet. Please contact the administrator.')
                return redirect('login')

            login(request, user)

            # role-based redirect
            if user.is_superuser or user.role == 'admin':
                return redirect('dashboard_admin')
            elif user.role == 'team':
                return redirect('dashboard_team')
            else:
                messages.error(request, 'Unknown role.')
                return redirect('login')
        else:
            messages.error(request, 'Invalid username or password.')

    return render(request, 'login.html')

def signup_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        role = request.POST.get('role')

        user = User.objects.create_user(
            username=username,
            password=password,
            role=role,
            is_active=True,
            is_approved=False
        )
        messages.success(request, "Account created! Wait for admin approval.")
        return redirect('login')

    return render(request, 'signup.html')

def custom_logout_view(request):
    logout(request)
    return redirect('face_page')

@login_required
@user_passes_test(is_admin)
def pending_users(request):
    users = User.objects.filter(is_approved=False)
    return render(request, 'pending_users.html', {'users': users})

@login_required
@user_passes_test(is_admin)
def approve_user(request, user_id):
    user = get_object_or_404(User, id=user_id)
    user.is_approved = True
    user.save()
    
    if user.role == 'team':
        messages.success(request, f"User {user.username} approved! Please assign a team to complete approval.")
        return redirect(reverse('add_team') + f'?user_id={user.id}')
        
    messages.success(request, f"User {user.username} approved successfully!")
    return redirect('pending_users')

@staff_member_required
def view_users(request):
    query = request.GET.get('q', '').strip()
    role = request.GET.get('role', '').strip()
    status = request.GET.get('status', '').strip()

    total_users_count = User.objects.count()
    admin_count = User.objects.filter(role='admin').count()
    team_count = User.objects.filter(Q(role='team') | Q(role='off_campus')).count()
    pending_count = User.objects.filter(is_approved=False).count()

    users = User.objects.all().select_related('team').order_by('-id')

    if query:
        users = users.filter(
            Q(username__icontains=query) |
            Q(email__icontains=query) |
            Q(team__name__icontains=query)
        )
    if role:
        users = users.filter(role=role)
    if status == 'active':
        users = users.filter(is_active=True)
    elif status == 'inactive':
        users = users.filter(is_active=False)

    paginator = Paginator(users, 10)
    page = request.GET.get('page')
    users = paginator.get_page(page)

    return render(request, 'view_users.html', {
        'users': users,
        'search_term': query,
        'selected_role': role,
        'selected_status': status,
        'total_users_count': total_users_count,
        'admin_count': admin_count,
        'team_count': team_count,
        'pending_count': pending_count,
    })

@staff_member_required
def delete_user(request, user_id):
    user = get_object_or_404(User, id=user_id)
    user.delete()
    return redirect('view_users')

@staff_member_required
def edit_user(request, user_id):
    user = get_object_or_404(User, id=user_id)

    if request.method == 'POST':
        user.username = request.POST.get('username')
        user.email = request.POST.get('email')
        user.role = request.POST.get('role')
        user.is_active = 'is_active' in request.POST
        user.save()
        messages.success(request, 'User updated successfully.')
        return redirect('view_users')

    return render(request, 'edit_user.html', {'user': user})

@login_required
@user_passes_test(is_admin)
def disapprove_user(request, user_id):
    user = get_object_or_404(User, id=user_id)
    user.is_approved = False
    user.save()
    return redirect('pending_users')

def manifest_view(request):
    fest_name = SystemSetting.get_setting('fest_name', 'Arts Fest')
    institution_name = SystemSetting.get_setting('institution_name', 'Campus / Institution')
    short_name = SystemSetting.get_setting('short_name', 'Fest Portal')
    manifest_data = {
        "name": f"{fest_name} - {institution_name}",
        "short_name": short_name,
        "description": f"{fest_name} Portal - {institution_name}",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0b0f19",
        "theme_color": "#033067",
        "orientation": "portrait",
        "icons": [
            {
                "src": "/static/images/favicon.svg",
                "sizes": "any",
                "type": "image/svg+xml",
                "purpose": "any maskable"
            },
            {
                "src": "/static/images/favicon.svg",
                "sizes": "192x192 512x512",
                "type": "image/svg+xml",
                "purpose": "any maskable"
            }
        ]
    }
    return JsonResponse(manifest_data)

@cache_control(max_age=86400, public=True)
def favicon_view(request):
    svg_path = os.path.join(settings.BASE_DIR, 'core', 'static', 'images', 'favicon.svg')
    if os.path.exists(svg_path):
        with open(svg_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return HttpResponse(content, content_type='image/svg+xml')
    return HttpResponse(status=404)

@cache_control(max_age=86400, public=True)
def fest_logo_view(request):
    svg_path = os.path.join(settings.BASE_DIR, 'core', 'static', 'images', 'fest_logo.svg')
    if os.path.exists(svg_path):
        with open(svg_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return HttpResponse(content, content_type='image/svg+xml')
    return HttpResponse(status=404)

@cache_control(max_age=86400, public=True)
def service_worker(request):
    sw_code = """
const CACHE_NAME = 'fest-pwa-v1';

const ASSETS_TO_CACHE = [
  '/',
  '/static/FDL.png',
  '/manifest.json'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS_TO_CACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME) return caches.delete(key);
        })
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        const responseClone = response.clone();
        caches.open(CACHE_NAME).then((cache) => {
          cache.put(event.request, responseClone);
        });
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
"""
    return HttpResponse(sw_code, content_type='application/javascript')


