from django.shortcuts import render
from django.db import transaction


# Create your views here.
# competition_app/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from .models import *
from .forms import ContestantForm, ParticipationForm, TeamForm
from .utils import get_grade, POINTS_FOR_RANK, POINTS_FOR_GRADE
from django.db.models import Count, Sum
from django.contrib.auth import logout
# views.py
from django.contrib.auth import get_user_model

# ==================== CONSTANTS ====================
# Individual Program Points
INDIVIDUAL_RANK_POINTS = {1: 3, 2: 2, 3: 1}
INDIVIDUAL_GRADE_POINTS = {'A+': 6, 'A': 5, 'B': 3, 'C': 1}

# Grade thresholds
GRADE_THRESHOLDS = [
    (90, 'A+'),
    (70, 'A'),
    (60, 'B'),
    (50, 'C'),
]

# ==================== HELPER FUNCTIONS ====================

def get_members_count_for_program(program):
       """Get members count for a program - defaults to 1 if not set"""
       return getattr(program, 'members_count', 1) or 1

def get_grade(marks):
    """Convert marks to grade based on thresholds"""
    if marks is None:
        return None
    for threshold, grade in GRADE_THRESHOLDS:
        if marks >= threshold:
            return grade
    return None


def calculate_group_rank_points(rank, members_count):
    """Calculate rank points for group programs based on contestant count"""
    multipliers = {1: 3, 2: 2, 3: 1}
    return multipliers.get(rank, 0) * members_count


def calculate_points(rank, grade, is_group=False, members_count=1):
    """Calculate total points based on rank and grade"""
    # Calculate rank points (only for top 3)
    rank_points = 0
    if rank and rank <= 3:
        if is_group:
            rank_points = calculate_group_rank_points(rank, members_count)
        else:
            rank_points = INDIVIDUAL_RANK_POINTS.get(rank, 0)
    
    # Calculate grade points (for any valid grade)
    grade_points = INDIVIDUAL_GRADE_POINTS.get(grade, 0) if grade else 0
    
    return rank_points, grade_points, rank_points + grade_points


def assign_ranks_with_ties(participations):
    """Assign ranks handling ties properly"""
    if not participations:
        return
    
    current_rank = 1
    prev_marks = None
    skip_count = 0
    
    for participant in participations:
        # Skip ranking if marks are 0 or None
        if participant.marks is None or participant.marks == 0:
            participant.rank = None
            participant.save(update_fields=['rank'])
            continue
        if prev_marks is not None and participant.marks < prev_marks:
            current_rank += skip_count
            skip_count = 1
        else:
            skip_count += 1
        
        participant.rank = current_rank
        participant.save(update_fields=['rank'])
        prev_marks = participant.marks


def award_points_to_team(participation, total_points):
    """Award points to team and mark as awarded"""
    team_points, _ = TeamPoints.objects.get_or_create(
        team=participation.contestant.team,
        defaults={'points': 0}
    )
    team_points.points += total_points
    team_points.save()
    
    participation.points_awarded = True
    participation.save(update_fields=['points_awarded'])


def recalculate_team_points(team, category_id=None):
    """Recalculate total points for a team (optionally within a specific category)."""
    participations = Participation.objects.filter(
        contestant__team=team,
        points_awarded=True,
        marks__isnull=False
    ).select_related('program', 'contestant__category')

    if category_id:
        participations = participations.filter(contestant__category_id=category_id)

    total_points = 0
    for p in participations:
        is_group = p.program.is_group
        contestant_count = getattr(p.program, 'members_count', 1) or 1
        _, _, points = calculate_points(p.rank, p.grade, is_group, contestant_count)
        total_points += points

    # We only store total points (not category-wise) to TeamPoints
    if not category_id:
        team_points, _ = TeamPoints.objects.get_or_create(team=team)
        team_points.points = total_points
        team_points.save()

    return total_points



User = get_user_model()

def is_admin(user):
    return user.is_superuser or user.role == 'admin' # or use your custom check

def face_page(request):
    programs = Program.objects.all()
    teams = Team.objects.all()
    contestants = Contestant.objects.all()
    context = {
        'programs': programs,
        'teams': teams,
        'contestants' : contestants
    }
    return render(request, 'face.html', context)

@login_required
@user_passes_test(is_admin)
def lock_user(request, user_id):
    user = get_object_or_404(User, id=user_id)

    if user.role == 'team':   # only lock team role users
        user.is_active = False
        user.save()

    return redirect('view_users')

@login_required
@user_passes_test(is_admin)
def unlock_user(request, user_id):
    user = get_object_or_404(User, id=user_id)

    if user.role == 'team':   # only unlock team role users
        user.is_active = True
        user.save()

    return redirect('view_users')


# @login_required
# def dashboard_admin(request):
#     if request.user.role != 'admin': return redirect('dashboard_team')
#     programs = Program.objects.all()
#     teams = Team.objects.all()
#     return render(request, 'dashboard_admin.html', {'programs': programs, 'teams': teams})

@login_required
def dashboard_admin(request):
    programs = Program.objects.all()
    teams = Team.objects.all()
    pending_users = User.objects.filter(is_approved=False)
    context = {
        'programs': programs,
        'teams': teams,
        'pending_users': pending_users,
    }
    return render(request, 'dashboard_admin.html', context)


@login_required
def dashboard_team(request):
    if request.user.role != 'team': return redirect('dashboard_admin')
    team = request.user.team
    # In your view
    contestants = Contestant.objects.filter(team=team).order_by('category', 'name')
    return render(request, 'dashboard_team.html', {
        'contestants': contestants,
        'team': team
        })

@login_required
def add_contestant(request):
    if request.method == 'POST':
        form = ContestantForm(request.POST)
        if form.is_valid():
            contestant = form.save(commit=False)
            contestant.team = request.user.team
            contestant.save()
            return redirect('dashboard_team')
    else:
        form = ContestantForm()
    return render(request, 'add_contestant.html', {'form': form})

@login_required
def enter_marks_summary(request):
    """Admin view to see marks summary and award points"""
    if request.user.role != 'admin':
        return redirect('dashboard_team')
    
    program_id = request.GET.get('program')
    programs = Program.objects.all().order_by('name')
    
    # Filter participations
    if program_id:
        participations = Participation.objects.filter(
            marks__isnull=False,
            program_id=program_id
        ).select_related('contestant__team', 'contestant__category', 'program').order_by('-marks')
        selected_program = get_object_or_404(Program, id=program_id)
        
        # Calculate and award points for this program
        calculate_and_award_points_for_program(selected_program)
    else:
        participations = Participation.objects.filter(
            marks__isnull=False
        ).select_related('contestant__team', 'contestant__category', 'program').order_by('program__name', '-marks')
        selected_program = None
        
        # Calculate for all programs
        for program in Program.objects.all():
            calculate_and_award_points_for_program(program)
    
    # Attach display points to participations
    for p in participations:
        contestant_count = get_members_count_for_program(p.program) if p.program.is_group else 1
        rank_pts, grade_pts, total_pts = calculate_points(
            p.rank, p.grade, p.program.is_group, contestant_count
        )
        p.rank_points = rank_pts
        p.grade_points = grade_pts
        p.total_points = total_pts if p.points_awarded else 0
    
    return render(request, 'enter_marks.html', {
        'participations': participations,
        'programs': programs,
        'selected_program': selected_program,
        'program_id': program_id,
    })

def calculate_and_award_points_for_program(program):
    """Calculate ranks, grades and award points for a specific program"""
    participations = Participation.objects.filter(
        program=program,
        marks__isnull=False
    ).select_related('contestant__team', 'contestant__category').order_by('-marks')
    
    if not participations:
        return
    
    # Assign ranks
    assign_ranks_with_ties(participations)
    
    # Award points
    contestant_count = get_members_count_for_program(program) if program.is_group else 1
    
    for p in participations:
        # Skip if marks are 0 or None
        if p.marks is None or p.marks == 0:
            p.rank = None
            p.grade = None
            p.points_awarded = False
            p.save()
            continue
        p.grade = get_grade(p.marks)
        
        if not p.points_awarded:
            _, _, total_points = calculate_points(
                p.rank, p.grade, program.is_group, contestant_count
            )
            
            if total_points > 0:
                award_points_to_team(p, total_points)
        
        p.save()


def assign_ranks_with_ties(participants):
    """
    Assign ranks to participants handling ties properly.
    For example: marks [90, 80, 80, 79] -> ranks [1, 2, 2, 3]
    """
    if not participants:
        return
    
    current_rank = 1
    previous_marks = None
    
    for participant in participants:
        if previous_marks is not None and participant.marks != previous_marks:
            # Different marks, increment rank by 1
            current_rank += 1
        
        participant.rank = current_rank
        previous_marks = participant.marks

@login_required
def team_marks_summary(request):
    """Team user view of their own results"""
    if request.user.role != 'team':
        return redirect('dashboard_admin')
    
    team = request.user.team
    participations = Participation.objects.filter(
        contestant__team=team,
        marks__isnull=False
    ).select_related('program', 'contestant').order_by('program__name', '-marks')
    
    # Attach display points
    for p in participations:
        contestant_count = get_members_count_for_program(p.program) if p.program.is_group else 1
        rank_pts, grade_pts, total_pts = calculate_points(
            p.rank, p.grade, p.program.is_group, contestant_count
        )
        p.rank_points = rank_pts
        p.grade_points = grade_pts
        p.total_points = total_pts if p.points_awarded else 0
    
    return render(request, 'team_marks_summary.html', {
        'team': team,
        'participations': participations,
    })

import xlwt
from django.http import HttpResponse

from django.db.models import F

@login_required
def results_view(request):
    """View all results"""
    participations = Participation.objects.filter(
        marks__isnull=False
    ).select_related('program', 'contestant', 'contestant__team').order_by('program__name', '-marks')
    
    return render(request, 'results.html', {'participations': participations})

@login_required
def export_excel(request):
    response = HttpResponse(content_type='application/ms-excel')
    response['Content-Disposition'] = 'attachment; filename="competition_results.xls"'

    wb = xlwt.Workbook(encoding='utf-8')
    ws = wb.add_sheet('Results')

    columns = ['Program', 'Contestant', 'Team', 'Marks', 'Grade', 'Rank']
    for col_num in range(len(columns)):
        ws.write(0, col_num, columns[col_num])

    rows = Participation.objects.filter(marks__isnull=False).values_list(
        'program__name', 'contestant__name', 'contestant__team__name',
        'marks', 'grade', 'rank'
    )
    for row_num, row in enumerate(rows, start=1):
        for col_num, value in enumerate(row):
            ws.write(row_num, col_num, value)

    wb.save(response)
    return response

def leaderboard(request):
    """Public leaderboard view with accurate recalculated points"""
    teams = Team.objects.all().order_by('name')
    
    team_data = []
    for team in teams:
        # Recalculate accurate points for each team
        total_points = recalculate_team_points(team)
        
        # Get participation statistics
        participations = Participation.objects.filter(contestant__team=team)
        awarded = participations.filter(points_awarded=True, marks__isnull=False)
        
        team_data.append({
            'team': team,
            'points': total_points,
            'total_participations': participations.count(),
            'winners_count': awarded.filter(rank__in=[1, 2, 3]).count(),
        })
    
    # Sort by points descending
    team_data.sort(key=lambda x: x['points'], reverse=True)
    
    # Add rank positions
    for i, data in enumerate(team_data, 1):
        data['position'] = i
    
    return render(request, 'leaderboard.html', {
        'teams': team_data,
        'top_three': team_data[:3] if len(team_data) >= 3 else team_data,
    })


from django.contrib.auth import authenticate, login
from django.contrib import messages


def landing_view(request):
    return render(request, 'landing.html')

from django.contrib.auth import authenticate, login
from django.shortcuts import redirect, render
from django.contrib import messages

def custom_login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)

        if user is not None:
            if not user.is_superuser and not user.is_approved:
                messages.error(request, 'Account pending approval by admin.')
                return redirect('login')

            login(request, user)

            # role-based redirect
            if user.is_superuser or user.role == 'admin':
                return redirect('dashboard_admin')
            elif user.role == 'team':
                return redirect('dashboard_team')
            elif user.role == 'off_campus':
                return redirect('dashboard_off_campus')
            else:
                messages.error(request, 'Unknown role.')
                return redirect('login')
        else:
            messages.error(request, 'Invalid username or password.')

    return render(request, 'login.html')

from django.contrib.auth import get_user_model
User = get_user_model()

def signup_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        role = request.POST.get('role')

        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already exists. Choose another.")
            return render(request, 'signup.html')

        user = User.objects.create_user(
            username=username,
            password=password,
            role=role,
            is_active=True,  # still needed to be True for Django auth
            is_approved=False  # requires admin approval
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
    return redirect('pending_users')

@login_required
@user_passes_test(is_admin)
def disapprove_user(request, user_id):
    user = get_object_or_404(User, id=user_id)
    user.is_approved = False
    user.save()
    return redirect('pending_users')

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.core.paginator import Paginator


User = get_user_model()

@user_passes_test(is_admin)
def view_users(request):
    query = request.GET.get('q')
    role = request.GET.get('role')

    users = User.objects.all()

    if query:
        users = users.filter(Q(username__icontains=query) | Q(email__icontains=query))
    if role:
        users = users.filter(role=role)

    paginator = Paginator(users, 10)  # 10 per page
    page = request.GET.get('page')
    users = paginator.get_page(page)

    return render(request, 'view_users.html', {
        'users': users,
        'search_term': query or '',
        'selected_role': role or '',
    })

@user_passes_test(is_admin)
def delete_user(request, user_id):
    user = get_object_or_404(User, id=user_id)
    user.delete()
    return redirect('view_users')


from django.contrib import messages

@user_passes_test(is_admin)
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


from .models import Program, Category


# add categroy by admin
from .models import Category

@login_required
def add_category(request):
    if not (request.user.is_superuser or getattr(request.user, 'role', None) == 'admin'):
        return redirect('dashboard_team')

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        competition_type = request.POST.get('competition_type', 'MAIN')

        if name:
            if Category.objects.filter(name__iexact=name).exists():
                messages.warning(request, f"Category '{name}' already exists.")
            else:
                Category.objects.create(name=name, competition_type=competition_type)
                messages.success(request, f"Category '{name}' added successfully.")
                return redirect('add_category')
        else:
            messages.error(request, "Category name cannot be empty.")

    categories = Category.objects.all().order_by('name')
    competition_types = Category.COMPETITION_TYPES
    return render(request, 'add_category.html', {
        'categories': categories,
        'competition_types': competition_types
    })



@login_required
def edit_category(request, category_id):
    if not (request.user.is_superuser or getattr(request.user, 'role', None) == 'admin'):
        return redirect('dashboard_team')
    
    category = get_object_or_404(Category, id=category_id)

    if request.method == 'POST':
        new_name = request.POST.get('name', '').strip()
        new_type = request.POST.get('type', category.competition_type)  # 👈 new line

        if new_name:
            category.name = new_name
            category.competition_type = new_type  # 👈 save the new type
            category.save()
            messages.success(request, f"Category '{new_name}' updated successfully.")
            return redirect('add_category')
        else:
            messages.error(request, "Name can't be empty.")

    return render(request, 'edit_category.html', {
        'category': category,
        'competition_types': Category.COMPETITION_TYPES
    })


@login_required
def delete_category(request, category_id):
    if request.user.role != 'admin':
        return redirect('dashboard_team')
    
    category = get_object_or_404(Category, id=category_id)
    category.delete()
    messages.success(request, "Category deleted.")
    return redirect('add_category')

from .models import Program

import pandas as pd
from django.core.files.storage import FileSystemStorage

@login_required
def add_program(request):
    if not (request.user.is_superuser or request.user.role == 'admin'):
        return redirect('dashboard_team')

    categories = Category.objects.all()
    programs = Program.objects.all().order_by('-id')

    if request.method == 'POST':
        # Check if it's a bulk upload
        if 'excel_file' in request.FILES:
            excel_file = request.FILES['excel_file']

            try:
                # Read Excel file with pandas
                df = pd.read_excel(excel_file)

                # Expecting columns: "name" and "category"
                for _, row in df.iterrows():
                    name = row.get("name")
                    category_name = row.get("category")

                    if name and category_name:
                        try:
                            category = Category.objects.get(name=category_name)
                            Program.objects.create(name=name, category=category)
                        except Category.DoesNotExist:
                            messages.warning(request, f"Category '{category_name}' not found for program '{name}'. Skipped.")
                messages.success(request, "Bulk upload completed successfully.")
            except Exception as e:
                messages.error(request, f"Error processing Excel file: {e}")

            return redirect('add_program')

        else:
            # Single entry form
            name = request.POST.get('name')
            category_id = request.POST.get('category')

            if name and category_id:
                category = Category.objects.get(id=category_id)
                members_count = request.POST.get('members_count') or 1
                Program.objects.create(name=name, category=category, members_count=members_count)
                messages.success(request, f"Program '{name}' added successfully under {category.name}.")
                return redirect('add_program')
            else:
                messages.error(request, "All fields are required.")

    return render(request, 'add_program.html', {'categories': categories, 'programs': programs})

from django.http import JsonResponse

@login_required
def toggle_is_group(request, program_id):
    if not (request.user.is_superuser or request.user.role == 'admin'):
        return JsonResponse({'error': 'Permission denied'}, status=403)

    program = get_object_or_404(Program, id=program_id)
    program.is_group = not program.is_group
    program.save()

    return JsonResponse({
        'success': True,
        'program_id': program.id,
        'is_group': program.is_group,
        'status': 'Group' if program.is_group else 'Individual'
    })



@login_required
def edit_program(request, program_id):
    if request.user.role != 'admin':
        return redirect('dashboard_team')

    program = get_object_or_404(Program, id=program_id)
    categories = Category.objects.all()

    if request.method == 'POST':
        name = request.POST.get('name').strip()
        category_id = request.POST.get('category')

        if name and category_id:
            category = get_object_or_404(Category, id=category_id)
            program.name = name
            program.category = category
            program.save()
            messages.success(request, "Program updated successfully.")
            return redirect('add_program')
        else:
            messages.error(request, "All fields are required.")

    return render(request, 'edit_program.html', {
        'program': program,
        'categories': categories
    })

@login_required
def delete_program(request, program_id):
    if request.user.role != 'admin':
        return redirect('dashboard_team')

    program = get_object_or_404(Program, id=program_id)
    program.delete()
    messages.success(request, "Program deleted successfully.")
    return redirect('add_program')

@login_required
def bulk_delete_programs(request):
    if request.user.role != 'admin':
        return redirect('dashboard_team')

    if request.method == "POST":
        program_ids = request.POST.getlist("program_ids")  # get selected IDs
        if program_ids:
            Program.objects.filter(id__in=program_ids).delete()
            messages.success(request, f"{len(program_ids)} programs deleted successfully.")
        else:
            messages.warning(request, "No programs selected.")
        return redirect('add_program')

    # If GET request → show programs list with checkboxes
    programs = Program.objects.all().order_by('name')
    return render(request, "bulk_delete_programs.html", {"programs": programs})

def program_list(request):
    programs = Program.objects.all().order_by('category__name', 'name')
    categories = Category.objects.all()

    context = {
        'programs':programs,
        'categories': categories
    }
    return render(request, 'program_list.html', context)


@login_required
def add_group_program(request):
    if not (request.user.is_superuser or request.user.role == 'admin'):
        return redirect('dashboard_team')

    categories = Category.objects.all()
    programs = Program.objects.filter(is_group=True).order_by('-id')

    if request.method == 'POST':
        name = request.POST.get('name')
        category_id = request.POST.get('category')

        if name and category_id:
            category = get_object_or_404(Category, id=category_id)
            Program.objects.create(name=name, category=category, is_group=True)
            messages.success(request, f"Group Program '{name}' added successfully.")
            return redirect('add_group_program')
        else:
            messages.error(request, "All fields are required.")

    return render(request, 'add_group_program.html', {'categories': categories, 'programs': programs})


@login_required
def assign_group_program(request):
    if not (request.user.is_superuser or request.user.role == 'admin'):
        return redirect('dashboard_team')

    categories = Category.objects.all()

    if request.method == 'POST':
        program_id = request.POST.get('program')
        participant_ids = request.POST.getlist('participants')

        if len(participant_ids) > 5:
            messages.error(request, "You can select a maximum of 5 participants.")
            return redirect('assign_group_program')

        program = get_object_or_404(Program, id=program_id)
        group_participation = GroupParticipation.objects.create(program=program)
        group_participation.contestants.set(participant_ids) 

        messages.success(request, "Participants assigned successfully.")
        return redirect('assign_group_program')

    return render(request, 'assign_group_program.html', {'categories': categories})


from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

@login_required
@csrf_exempt
def get_group_programs(request):
    category_id = request.POST.get('category_id')
    programs = Program.objects.filter(category_id=category_id, is_group=True)
    program_list = [{"id": p.id, "name": p.name} for p in programs]
    return JsonResponse({"programs": program_list})

@login_required
@csrf_exempt
def get_participants_by_category(request):
    category_id = request.POST.get('category_id')
    contestants = Contestant.objects.filter(category_id=category_id)
    contestant_list = [{"id": c.id, "name": c.name} for c in contestants]
    return JsonResponse({"contestants": contestant_list})


@login_required
def participant_list(request):
    user = request.user
    team_id = request.GET.get('team_id')
    category_id = request.GET.get('category_id')

    teams = Team.objects.all()
    categories = Category.objects.all()
    participants = Contestant.objects.select_related('team', 'category').order_by('chest_no')

    # 👇 If the logged-in user is a team user, filter to only their team participants
    if hasattr(user, 'team'):
        participants = participants.filter(team=user.team)
        team_id = user.team.id  # Fix context
    else:
        # For admin users, allow filtering
        if team_id:
            participants = participants.filter(team_id=team_id)
        if category_id:
            participants = participants.filter(category_id=category_id)

    return render(request, 'participants_list.html', {
        'teams': teams,
        'categories': categories,
        'participants': participants,
        'selected_team_id': int(team_id) if team_id else None,
        'selected_category_id': int(category_id) if category_id else None
    })

@login_required
def participants_by_category(request):
    user = request.user
    
    # Get all categories and participants
    categories = Category.objects.all().order_by('name')
    participants = Contestant.objects.select_related('team', 'category').order_by('chest_no')
    
    # If the logged-in user is a team user, filter to only their team participants
    if hasattr(user, 'team'):
        participants = participants.filter(team=user.team)
    
    # Group participants by category
    participants_by_category = {}
    for category in categories:
        category_participants = participants.filter(category=category)
        if category_participants.exists():
            participants_by_category[category] = category_participants
    
    return render(request, 'participants_by_category.html', {
        'participants_by_category': participants_by_category,
        'total_participants': participants.count(),
    })


@login_required
def participants_by_team(request):
    user = request.user
    
    # Get all teams and participants
    teams = Team.objects.all().order_by('name')
    participants = Contestant.objects.select_related('team', 'category').order_by('chest_no')
    
    # If the logged-in user is a team user, show only their team
    if hasattr(user, 'team'):
        teams = Team.objects.filter(id=user.team.id)
        participants = participants.filter(team=user.team)
    
    # Group participants by team
    participants_by_team = {}
    for team in teams:
        team_participants = participants.filter(team=team)
        if team_participants.exists():
            participants_by_team[team] = team_participants
    
    return render(request, 'participants_by_team.html', {
        'participants_by_team': participants_by_team,
        'total_participants': participants.count(),
    })


import pandas as pd
from django.contrib import messages
from .forms import ContestantForm
from .models import Contestant, Team, Category

def add_participant(request):
    if request.method == 'POST':
        # --- Bulk Upload Excel ---
        if 'excel_file' in request.FILES:
            excel_file = request.FILES['excel_file']
            try:
                df = pd.read_excel(excel_file)

                # Expect columns: name, team, category
                for _, row in df.iterrows():
                    name = row.get("name")
                    team_name = row.get("team")
                    category_name = row.get("category")

                    if not (name and team_name and category_name):
                        continue  # skip incomplete rows

                    try:
                        team = Team.objects.get(name=team_name)
                        category = Category.objects.get(name=category_name)

                        Contestant.objects.create(
                            name=name,
                            team=team,
                            category=category,
                            # chest_no auto-assigned in save()
                            # total_points default=0
                        )
                    except Team.DoesNotExist:
                        messages.warning(request, f"Team '{team_name}' not found. Skipped {name}.")
                    except Category.DoesNotExist:
                        messages.warning(request, f"Category '{category_name}' not found. Skipped {name}.")

                messages.success(request, "Bulk participant upload successful.")
            except Exception as e:
                messages.error(request, f"Error processing Excel: {e}")

            return redirect('participant_list')

        # --- Single Form Entry ---
        else:
            form = ContestantForm(request.POST)
            if form.is_valid():
                form.save()
                messages.success(request, "Participant added successfully.")
                return redirect('participant_list')
    else:
        form = ContestantForm()

    return render(request, 'participant_form.html', {'form': form})


def edit_participant(request, id):
    participant = get_object_or_404(Contestant, id=id)
    if request.method == 'POST':
        form = ContestantForm(request.POST, instance=participant)
        if form.is_valid():
            form.save()
            return redirect('participant_list')
    else:
        form = ContestantForm(instance=participant)
    return render(request, 'participant_form.html', {'form': form})

def delete_participant(request, id):
    participant = get_object_or_404(Contestant, id=id)
    participant.delete()
    return redirect('participant_list')

def participants_list(request):
    participants = Contestant.objects.select_related('team', 'category').order_by('chest_no')
    return render(request, 'participants_list.html', {'participants': participants})


def add_team(request):
    form = TeamForm(request.POST or None)
    if form.is_valid():
        form.save()
        return redirect('add_team')
    teams = Team.objects.all()
    return render(request, 'add_team_modal.html', {'form': form, 'teams': teams})

def edit_team(request, team_id):
    team = get_object_or_404(Team, id=team_id)
    form = TeamForm(request.POST or None, instance=team)
    if form.is_valid():
        form.save()
        return redirect('add_team')
    return render(request, 'edit_team.html', {'form': form, 'team': team})

def delete_team(request, team_id):
    team = get_object_or_404(Team, id=team_id)
    team.delete()
    return redirect('add_team')


# views.py
from .forms import ParticipationForm

# views.py
from django.http import JsonResponse
from .models import Program, Participation, Contestant, Category

def get_programs_for_contestant(request):
    contestant_id = request.GET.get('contestant_id')
    category_id = request.GET.get('category_id')

    if not contestant_id or not category_id:
        return JsonResponse({'programs': []})

    # programs already assigned to contestant
    assigned_programs = Participation.objects.filter(
        contestant_id=contestant_id
    ).values_list('program_id', flat=True)

    try:
        contestant = Contestant.objects.get(id=contestant_id)
        selected_category = Category.objects.get(id=category_id)
    except (Contestant.DoesNotExist, Category.DoesNotExist):
        return JsonResponse({'programs': []})

    # Logic: contestant category + general
    if contestant.category.name.lower() == "junior":
        categories_to_include = ["Junior", "General"]
    elif contestant.category.name.lower() == "senior":
        categories_to_include = ["Senior", "General"]
    else:  # if contestant is General (rare case)
        categories_to_include = ["General"]

    programs = Program.objects.filter(
        category__name__in=categories_to_include
    ).exclude(id__in=assigned_programs)

    return JsonResponse({
        'programs': list(programs.values('id', 'name'))
    })




from django.http import JsonResponse
from .models import Contestant, Category

def get_contestants(request):
    team_id = request.GET.get('team_id')
    category_id = request.GET.get('category_id')

    contestants = Contestant.objects.none()

    if team_id and category_id:
        try:
            category = Category.objects.get(id=category_id)

            if category.name.lower() == "general":
                # Fetch contestants from Junior + Senior
                contestants = Contestant.objects.filter(
                    team_id=team_id,
                    category__name__in=["JUNIOR", "SENIOR"]
                )
            else:
                # Fetch contestants only in that category
                contestants = Contestant.objects.filter(
                    team_id=team_id,
                    category=category
                )
        except Category.DoesNotExist:
            pass

    return JsonResponse({
        'contestants': list(contestants.values('id', 'name'))
    })



@login_required
def assign_programs(request):
    teams = Team.objects.all()
    categories = Category.objects.all()

    contestants = Contestant.objects.none()
    programs = Program.objects.none()

    team_id = request.GET.get('team')
    category_id = request.GET.get('category')

    if team_id and category_id:
        try:
            selected_category = Category.objects.get(id=category_id)

            if selected_category.name.lower() == "general":
                # contestants from Junior + Senior
                contestants = Contestant.objects.filter(
                    team_id=team_id,
                    category__name__in=["JUNIOR", "SENIOR", "SUBJUNIOR"]
                )
                # programs only from General
                programs = Program.objects.filter(category=selected_category)
            else:
                contestants = Contestant.objects.filter(
                    team_id=team_id,
                    category=selected_category
                )
                programs = Program.objects.filter(category=selected_category)

        except Category.DoesNotExist:
            pass

    if request.method == 'POST':
        contestant_id = request.POST.get('contestant')
        selected_programs = request.POST.getlist('programs')

        if len(selected_programs) > 5:
            messages.error(request, "You can only select up to 5 programs.")
        else:
            for prog_id in selected_programs:
                Participation.objects.get_or_create(
                    contestant_id=contestant_id,
                    program_id=prog_id
                )
            messages.success(request, "Programs assigned successfully!")
            return redirect('assign_programs')

    return render(request, 'assign_programs.html', {
        'teams': teams,
        'categories': categories,
        'contestants': contestants,
        'programs': programs,
    })


@login_required
def edit_assigned_programs(request, contestant_id):
    contestant = get_object_or_404(Contestant, id=contestant_id)

    # ✅ Get programs in contestant's category OR "General"
    all_programs = Program.objects.filter(
        Q(category=contestant.category) | Q(category__name="GENERAL")
    )

    # Already assigned
    assigned_programs = Participation.objects.filter(contestant=contestant).values_list('program_id', flat=True)

    if request.method == "POST":
        selected_program_ids = request.POST.getlist('programs')

        # Clear old assignments
        Participation.objects.filter(contestant=contestant).delete()

        # Save new assignments
        for program_id in selected_program_ids:
            Participation.objects.create(contestant=contestant, program_id=program_id)

        messages.success(request, "Programs updated successfully.")
        return redirect("assigned_programs")  # adjust to your URL name

    return render(request, "edit_assigned_programs.html", {
        "contestant": contestant,
        "all_programs": all_programs,   # ✅ category + GENERAL
        "assigned_program_ids": list(assigned_programs),
    })

from django.shortcuts import render
from .models import Participation
from django.shortcuts import render
from .models import Participation, Team, Category

@login_required
def view_assigned_programs(request):
    team_id = request.GET.get('team')
    category_id = request.GET.get('category')

    participations = Participation.objects.select_related(
        'contestant__team', 'contestant__category', 'program__category'
    )

    # Force filter by team if user is a team user
    if hasattr(request.user, 'team'):
        team_id = request.user.team.id
        participations = participations.filter(contestant__team_id=team_id)
    elif team_id:
        participations = participations.filter(contestant__team_id=team_id)

    if category_id:
        participations = participations.filter(
            Q(contestant__category_id=category_id) | Q(program__category_id=category_id)
        )

    context = {
        'participations': participations.order_by('contestant__team__name'),
        'teams': Team.objects.all(),
        'categories': Category.objects.all(),
        'selected_team': int(team_id) if team_id else '',
        'selected_category': int(category_id) if category_id else '',
    }
    return render(request, 'assigned_programs.html', context)

from django.utils import timezone


@login_required
def download_participation_list_pdf(request):
    """Download Participation List PDF"""
    user = request.user

    # Fetch contestants sorted by team, then category, then chest_no
    participants = Contestant.objects.select_related(
        'team', 'category', 'participation__program'
    ).order_by('team__name', 'category__name', 'chest_no')

    # If team user → filter
    if hasattr(user, 'team'):
        participants = participants.filter(team=user.team)

    # File name
    filename = "participation_list.pdf"
    if hasattr(user, 'team'):
        filename = f"{user.team.name}_participation_list.pdf"

    # Context
    context = {
        'fest_name': "Annual Arts Fest 2025",   # 👈 set your fest name dynamically if stored
        'date': timezone.now().strftime("%d-%m-%Y"),
        'participants': participants,
        'is_team_user': hasattr(user, 'team'),
        'team_name': user.team.name if hasattr(user, 'team') else None
    }

    # Generate PDF
    template_path = 'participation_list_pdf.html'
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    template = get_template(template_path)
    html = template.render(context)
    pisa_status = pisa.CreatePDF(html, dest=response)

    if pisa_status.err:
        return HttpResponse('We had some errors <pre>' + html + '</pre>')
    return response

@login_required
def delete_assigned_program(request, participation_id):
    participation = get_object_or_404(Participation, id=participation_id)
    participation.delete()
    messages.success(request, "Program assignment removed successfully.")
    return redirect('assigned_programs')  # redirect to the list view




from django.shortcuts import render
from core.models import Participation, Program

def view_results(request):
    """Public view of all program results"""
    # Fetch programs with results
    programs = Program.objects.filter(participation__marks__isnull=False).distinct().order_by('name')

    program_results = []
    for program in programs:
        results = (
            Participation.objects
            .filter(program=program, marks__isnull=False)
            .select_related('contestant', 'contestant__team')
            .order_by('rank')
        )

        # Get members count for this program
        members_count = get_members_count_for_program(program) if program.is_group else 1

        # Add calculated points for display
        for p in results:
            if p.points_awarded and p.marks and p.marks > 0:
                rank_pts, grade_pts, total_pts = calculate_points(
                    p.rank, 
                    p.grade, 
                    program.is_group, 
                    members_count
                )
                p.rank_points = rank_pts
                p.grade_points = grade_pts
                p.total_points = total_pts
            else:
                p.rank_points = 0
                p.grade_points = 0
                p.total_points = 0

        program_results.append({
            'program': program,
            'results': results,
            'is_group': program.is_group,
            'members_count': members_count,
            'program_total_points': sum(p.total_points for p in results)
        })


    # Fetch categories with results
    categories = Category.objects.filter(
        program__participation__marks__isnull=False
    ).distinct().order_by('name')

    return render(
        request,
        'view_results.html',
        {
            'program_results': program_results, 
            'categories': categories
        }
    )

from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from .models import Program, Participation

def program_result_pdf(request, program_id):
    program = get_object_or_404(Program, id=program_id)

    results = (
        Participation.objects
        .filter(program=program, marks__isnull=False)
        .select_related('contestant', 'contestant__team')
        .order_by('rank')
    )

    # Calculate members count
    members_count = get_members_count_for_program(program) if program.is_group else 1

    # Prepare PDF response
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{program.name}_results.pdf"'

    doc = SimpleDocTemplate(response, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []

    # Title
    elements.append(Paragraph(f"<b>{program.name.upper()}</b>", styles['Title']))
    elements.append(Spacer(1, 12))

    # Table header
    data = [["Rank", "Chest No", "Name", "Team", "Grade", "Points"]]

    # Table rows
    for r in results:
        rank_pts, grade_pts, total_pts = calculate_points(
            r.rank, 
            r.grade, 
            program.is_group, 
            members_count
        )
        data.append([
            r.rank or "-",
            r.contestant.chest_no,
            r.contestant.name.upper(),
            r.contestant.team.name.upper() if r.contestant.team else "-",
            r.grade or "-",
            f"{total_pts:.2f}"
        ])

    # Build table
    table = Table(data, colWidths=[40, 50, 140, 120, 50, 60])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
    ]))

    elements.append(table)

    # Optional total row
    elements.append(Spacer(1, 12))

      # ---------- WATERMARK FUNCTION ----------
    def add_watermark(canvas, doc):
        canvas.saveState()
        canvas.setFont('Helvetica-Bold', 60)
        canvas.setFillColorRGB(0.9, 0.9, 0.9, alpha=0.2)  # Light gray, transparent
        canvas.translate(300, 600)
        canvas.rotate(45)
        canvas.drawCentredString(0, 0, "FELIZ DIA'25")
        canvas.restoreState()

    # Build PDF with watermark
    doc.build(elements, onFirstPage=add_watermark, onLaterPages=add_watermark)
    return response



from django.template.loader import get_template
from django.http import HttpResponse
from xhtml2pdf import pisa

def render_to_pdf(template_src, context_dict={}):
    template = get_template(template_src)
    html = template.render(context_dict)
    response = HttpResponse(content_type='application/pdf')
    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('We had some errors <pre>' + html + '</pre>')
    return response

def results_pdf(request):
    programs = Program.objects.filter(participation__marks__isnull=False).distinct()

    program_results = []
    for program in programs:
        results = (
            Participation.objects
            .filter(program=program, marks__isnull=False)
            .select_related('contestant', 'contestant__team')
            .order_by('rank')
        )

        # Get members count
        members_count = get_members_count_for_program(program) if program.is_group else 1

        # Add total_points for each participant
        for p in results:
            if p.points_awarded and p.marks and p.marks > 0:
                rank_pts, grade_pts, total_pts = calculate_points(
                    p.rank,
                    p.grade,
                    program.is_group,
                    members_count
                )
                p.total_points = total_pts
            else:
                p.total_points = 0

        program_results.append({
            'program': program,
            'results': results,
        })

    context = {'program_results': program_results}
    return render_to_pdf('results_pdf.html', context)



from django.forms import modelformset_factory
from django.db import transaction
from django.http import JsonResponse
from .models import Category, Program, Participation, TeamPoints
from .forms import MarkEntryForm



from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import transaction
from django.forms import modelformset_factory
from .models import Category, Program, Participation
from .forms import MarkEntryForm
from django.contrib.auth.decorators import login_required

@login_required
def add_marks(request):
    """Add or edit marks for participants"""
    if request.user.role != 'admin':
        messages.error(request, 'You do not have permission to access this page.')
        return redirect('dashboard_team')
    
    category_id = request.GET.get('category')
    program_id = request.GET.get('program')
    
    categories = Category.objects.all().order_by('name')
    programs = Program.objects.none()
    participations = Participation.objects.none()
    
    if category_id:
        programs = Program.objects.filter(category_id=category_id).order_by('name')
    
    if program_id:
        participations = Participation.objects.filter(
            program_id=program_id
        ).select_related('contestant', 'contestant__team', 'program').order_by('contestant__chest_no')
    
    ParticipationFormSet = modelformset_factory(
        Participation,
        form=MarkEntryForm,
        extra=0,
        can_delete=False
    )
    
    if request.method == 'POST':
        formset = ParticipationFormSet(request.POST, queryset=participations)
        if formset.is_valid():
            with transaction.atomic():
                saved_count = 0
                for form in formset:
                    instance = form.save(commit=False)
                    if instance.marks is not None:
                        if not instance.marks_added_at:
                            instance.marks_added_at = timezone.now()
                        instance.save()
                        saved_count += 1
                
                # Recalculate for this program
                if program_id:
                    program = Program.objects.get(id=program_id)
                    # ✅ Assign result number if not already assigned
                    if not program.result_number:
                        latest_number = Program.objects.filter(
                            result_number__isnull=False
                        ).aggregate(models.Max('result_number'))['result_number__max'] or 0
                        program.result_number = latest_number + 1
                        program.save()
                    calculate_and_award_points_for_program(program)
                
                messages.success(request, f'Successfully saved marks for {saved_count} participants!')
            
            return redirect(f"{request.path}?category={category_id}&program={program_id}")
    else:
        formset = ParticipationFormSet(queryset=participations)
    
    return render(request, 'add_marks.html', {
        'categories': categories,
        'programs': programs,
        'formset': formset,
        'selected_category': category_id,
        'selected_program': program_id,
        'participations': participations,
    })

@login_required
def undo_points(request, participation_id):
    if request.user.role != 'admin':
        messages.error(request, 'You do not have permission to perform this action.')
        return redirect('dashboard_team')

    try:
        participation = Participation.objects.select_related(
            'contestant__team', 'program'
        ).get(id=participation_id)

        if not participation.points_awarded:
            messages.warning(request, "Points were not awarded for this participant.")
            return redirect(request.META.get('HTTP_REFERER', 'add_marks'))

        # Calculate total points that were awarded
        is_group = participation.program.is_group
        contestant_count = get_members_count_for_program(participation.program) if is_group else 1
        rank_pts, grade_pts, total_points = calculate_points(
            participation.rank, 
            participation.grade, 
            is_group, 
            contestant_count
        )

        # Deduct from team
        team = participation.contestant.team
        team_points, _ = TeamPoints.objects.get_or_create(team=team)
        team_points.points = max(0, team_points.points - total_points)
        team_points.save()

        # Reset participant fields
        participation.rank = None
        participation.grade = None
        participation.marks = None
        participation.points_awarded = False
        participation.save()

        # 🔥 IMPORTANT: Recalculate rankings for this program
        program = participation.program
        calculate_and_award_points_for_program(program)

        messages.success(request, f"✅ Points and marks for {participation.contestant.name} in {participation.program.name} have been undone.")

    except Participation.DoesNotExist:
        messages.error(request, "Participation not found.")

    return redirect(request.META.get('HTTP_REFERER', 'add_marks'))

@login_required
def recalculate_all_rankings(request):
    """Recalculate rankings for all programs - fixes zero marks issue"""
    if request.user.role != 'admin':
        messages.error(request, 'You do not have permission.')
        return redirect('dashboard_team')
    
    # Recalculate for all programs
    for program in Program.objects.all():
        calculate_and_award_points_for_program(program)
    
    messages.success(request, "✅ All rankings have been recalculated!")
    return redirect('enter_marks_summary')


def award_points_to_team(participant, total_points):
    """Award points to team and mark participant as points awarded"""
    team = participant.contestant.team
    team_points, created = TeamPoints.objects.get_or_create(team=team, defaults={'points': 0})
    team_points.points += total_points
    team_points.save()
    team.total_points += total_points
    team.save()
    participant.points_awarded = True


from django.db.models import Avg

def calculate_rankings_and_points(category_id, program_id):
    """
    Calculate rankings and award points for a specific program in a category.
    Handles both individual and group programs with proper tie handling.
    """
    try:
        # Get program instance to check if group or individual
        program = Program.objects.get(id=program_id)
        is_group_program = program.is_group
        
        participants = Participation.objects.filter(
            contestant__category_id=category_id,
            program_id=program_id,
            marks__isnull=False
        ).select_related('contestant', 'contestant__team').order_by('-marks', 'contestant__chest_no')
        
        # Reset all rankings first
        Participation.objects.filter(
            contestant__category_id=category_id,
            program_id=program_id
        ).update(rank=None, grade=None)
        
        # Apply proper ranking with ties
        assign_ranks_with_ties(participants)
        
        for participant in participants:
            participant.grade = get_grade(participant.marks)
            
            if not participant.points_awarded:
                category_name = participant.contestant.category.name if participant.contestant.category else None
                total_points = calculate_points(participant.rank, participant.grade, is_group_program, category_name)
                
                if total_points > 0:
                    award_points_to_team(participant, total_points)
            
            participant.save()
            
    except Exception as e:
        print(f"Error in calculate_rankings_and_points: {e}")
        raise







@login_required
def get_programs_by_category(request):
    """
    AJAX view to get programs filtered by category
    """
    category_id = request.GET.get('category_id')
    programs = []

    if category_id:
        try:
            programs_qs = Program.objects.filter(
                category_id=int(category_id)
            ).order_by('name')
            programs = [{'id': p.id, 'name': p.name} for p in programs_qs]
        except (ValueError, TypeError):
            pass

    return JsonResponse({'programs': programs})


from django.db.models import Count, Q, Sum
from .models import Team, TeamPoints, Participation



@login_required
def team_leaderboard(request):
    """Display team leaderboard with accurate points"""
    teams = Team.objects.all().order_by('name')
    
    team_stats = []
    for team in teams:
        # Recalculate accurate points
        total_points = recalculate_team_points(team)
        
        # Get statistics
        participations = Participation.objects.filter(contestant__team=team)
        awarded = participations.filter(points_awarded=True, marks__isnull=False)
        
        team_stats.append({
            'team': team,
            'total_points': total_points,
            'total_participations': participations.count(),
            'marked_participations': participations.filter(marks__isnull=False).count(),
            'awarded_participations': awarded.count(),
            'first_place': awarded.filter(rank=1).count(),
            'second_place': awarded.filter(rank=2).count(),
            'third_place': awarded.filter(rank=3).count(),
            'grade_aplus': awarded.filter(grade='A+').count(),
            'grade_a': awarded.filter(grade='A').count(),
            'grade_b': awarded.filter(grade='B').count(),
            'grade_c': awarded.filter(grade='C').count(),
        })
    
    # Sort by points
    team_stats.sort(key=lambda x: x['total_points'], reverse=True)
    
    # Add positions
    for i, stat in enumerate(team_stats, 1):
        stat['position'] = i
    
    return render(request, 'team_leaderboard.html', {
        'team_stats': team_stats,
        'top_teams': team_stats[:3],
        'total_teams': len(team_stats),
        'total_points_distributed': sum(s['total_points'] for s in team_stats),
    })


from collections import defaultdict

@login_required
def team_detail(request, team_id):
    """Detailed view of a team's performance"""
    team = get_object_or_404(Team, id=team_id)
    
    # Recalculate points
    total_points = recalculate_team_points(team)
    
    # Get participations
    participations = Participation.objects.filter(
        contestant__team=team,
        marks__isnull=False
    ).select_related('program', 'contestant').order_by('-marks')
    
    # Attach display points
    for p in participations:
        contestant_count = get_members_count_for_program(p.program) if p.program.is_group else 1
        rank_pts, grade_pts, total_pts = calculate_points(
            p.rank, p.grade, p.program.is_group, contestant_count
        )
        p.rank_points = rank_pts
        p.grade_points = grade_pts
        p.total_points = total_pts if p.points_awarded else 0
    
    winners = participations.filter(rank__in=[1, 2, 3], points_awarded=True)
    
    return render(request, 'team_detail.html', {
        'team': team,
        'team_points': total_points,
        'participations': participations,
        'winners': winners,
        'total_participations': participations.count(),
        'total_winners': winners.count(),
    })



from django.http import HttpResponse
from django.template.loader import get_template
from xhtml2pdf import pisa
from .models import Contestant

@login_required
def download_participants_pdf(request):
    user = request.user
    
    # Get participants based on user role
    participants = Contestant.objects.select_related('team', 'category').order_by('chest_no')
    
    # If the logged-in user is a team user, filter to only their team participants
    if hasattr(user, 'team'):
        participants = participants.filter(team=user.team)
        filename = f"{user.team.name}_participants.pdf"
    else:
        # Admin users can download all participants
        filename = "all_participants.pdf"
    
    template_path = 'pdf_template.html'
    context = {
        'participants': participants,
        'user': user,
        'is_team_user': hasattr(user, 'team'),
        'team_name': user.team.name if hasattr(user, 'team') else None
    }
    
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    template = get_template(template_path)
    html = template.render(context)
    
    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('We had some errors <pre>' + html + '</pre>')
    return response


# Optional: Create separate PDF download functions for specific views
@login_required
def download_category_participants_pdf(request):
    user = request.user
    category_id = request.GET.get('category_id')
    
    participants = Contestant.objects.select_related('team', 'category').order_by('chest_no')
    
    # Filter by team if team user
    if hasattr(user, 'team'):
        participants = participants.filter(team=user.team)
    
    # Filter by category if specified
    if category_id:
        participants = participants.filter(category_id=category_id)
        try:
            category = Category.objects.get(id=category_id)
            filename = f"{category.name}_participants.pdf"
        except Category.DoesNotExist:
            filename = "category_participants.pdf"
    else:
        filename = "participants_by_category.pdf"
    
    template_path = 'pdf_template.html'
    context = {
        'participants': participants,
        'user': user,
        'is_team_user': hasattr(user, 'team'),
        'team_name': user.team.name if hasattr(user, 'team') else None,
        'category_filter': category.name if category_id else None
    }
    
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    template = get_template(template_path)
    html = template.render(context)
    
    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('We had some errors <pre>' + html + '</pre>')
    return response


@login_required
def download_team_participants_pdf(request):
    user = request.user
    team_id = request.GET.get('team_id')
    
    participants = Contestant.objects.select_related('team', 'category').order_by('chest_no')
    
    # If team user, they can only download their own team
    if hasattr(user, 'team'):
        participants = participants.filter(team=user.team)
        filename = f"{user.team.name}_participants.pdf"
    else:
        # Admin can download specific team or all teams
        if team_id:
            participants = participants.filter(team_id=team_id)
            try:
                team = Team.objects.get(id=team_id)
                filename = f"{team.name}_participants.pdf"
            except Team.DoesNotExist:
                filename = "team_participants.pdf"
        else:
            filename = "participants_by_team.pdf"
    
    template_path = 'pdf_template.html'
    context = {
        'participants': participants,
        'user': user,
        'is_team_user': hasattr(user, 'team'),
        'team_name': user.team.name if hasattr(user, 'team') else None,
        'team_filter': team.name if team_id else None
    }
    
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    template = get_template(template_path)
    html = template.render(context)
    
    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('We had some errors <pre>' + html + '</pre>')
    return response


@login_required
def program_participants(request):
    """Show participants for a specific program"""
    user = request.user
    program_id = request.GET.get('program_id')
    
    # Get all programs for the dropdown
    programs = Program.objects.all().order_by('name')
    participants = None
    selected_program = None
    
    if program_id:
        try:
            selected_program = Program.objects.get(id=program_id)
            participants = Contestant.objects.filter(
                program=selected_program
            ).select_related('team', 'category').order_by('chest_no')
            
            # If team user, filter to only their team participants
            if hasattr(user, 'team'):
                participants = participants.filter(team=user.team)
                
        except Program.DoesNotExist:
            selected_program = None
            participants = None
    
    return render(request, 'program_participants.html', {
        'programs': programs,
        'participants': participants,
        'selected_program': selected_program,
        'selected_program_id': int(program_id) if program_id else None,
    })


@login_required
def download_green_room_pdf(request, program_id):
    """Download Green Room Sign Sheet PDF"""
    try:
        program = Program.objects.get(id=program_id)
    except Program.DoesNotExist:
        return HttpResponse('Program not found', status=404)

    user = request.user
    participants = Contestant.objects.filter(
        participation__program=program
    ).select_related('team', 'category').order_by('chest_no')

    # Filter by team if team user
    if hasattr(user, 'team'):
        participants = participants.filter(team=user.team)
        filename = f"{program.name}_{user.team.name}_green_room.pdf"
    else:
        filename = f"{program.name}_green_room.pdf"

    template_path = 'green_room_pdf.html'
    context = {
        'program': program,
        'participants': participants,
        'user': user,
        'is_team_user': hasattr(user, 'team'),
        'team_name': user.team.name if hasattr(user, 'team') else None
    }

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    template = get_template(template_path)
    html = template.render(context)

    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('We had some errors <pre>' + html + '</pre>')
    return response


@login_required
def green_room_list(request, program_id):
    """Show Green Room Sign Sheet as normal Django page (HTML table)"""
    try:
        program = Program.objects.get(id=program_id)
    except Program.DoesNotExist:
        return HttpResponse('Program not found', status=404)

    user = request.user
    participants = Contestant.objects.filter(
        participation__program=program
    ).select_related('team', 'category').order_by('chest_no')

    # Filter if team user
    if hasattr(user, 'team'):
        participants = participants.filter(team=user.team)

    context = {
        'program': program,
        'participants': participants,
        'is_team_user': hasattr(user, 'team'),
        'team_name': user.team.name if hasattr(user, 'team') else None
    }
    return render(request, 'green_room_list.html', context)



@login_required
def download_call_list_pdf(request, program_id):
    """Download Call List PDF"""
    try:
        program = Program.objects.get(id=program_id)
    except Program.DoesNotExist:
        return HttpResponse('Program not found', status=404)
    
    user = request.user
    participants = Contestant.objects.filter(
         participation__program=program
    ).select_related('team', 'category').order_by('chest_no')
    
    # Filter by team if team user
    if hasattr(user, 'team'):
        participants = participants.filter(team=user.team)
        filename = f"{program.name}_{user.team.name}_call_list.pdf"
    else:
        filename = f"{program.name}_call_list.pdf"
    
    template_path = 'call_list_pdf.html'
    context = {
        'program': program,
        'participants': participants,
        'user': user,
        'is_team_user': hasattr(user, 'team'),
        'team_name': user.team.name if hasattr(user, 'team') else None
    }
    
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    template = get_template(template_path)
    html = template.render(context)
    
    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('We had some errors <pre>' + html + '</pre>')
    return response


@login_required
def download_valuation_form_pdf(request, program_id):
    """Download Valuation Form PDF"""
    try:
        program = Program.objects.get(id=program_id)
    except Program.DoesNotExist:
        return HttpResponse('Program not found', status=404)
    
    user = request.user
    participants = Contestant.objects.filter(
         participation__program=program
    ).select_related('team', 'category').order_by('chest_no')
    
    # Filter by team if team user
    if hasattr(user, 'team'):
        participants = participants.filter(team=user.team)
        filename = f"{program.name}_{user.team.name}_valuation.pdf"
    else:
        filename = f"{program.name}_valuation.pdf"
    
    template_path = 'valuation_form.html'
    context = {
        'program': program,
        'participants': participants,
        'user': user,
        'is_team_user': hasattr(user, 'team'),
        'team_name': user.team.name if hasattr(user, 'team') else None
    }
    
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    template = get_template(template_path)
    html = template.render(context)
    
    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('We had some errors <pre>' + html + '</pre>')
    return response


def list_page(request):
    return render(request, 'list_page.html')

@login_required
def download_all_call_lists_pdf(request):
    """Download Call List PDF for all programs"""
    user = request.user
    
    # Fetch all programs
    programs = Program.objects.all().order_by('name')

    # Collect participants for each program
    program_participants = []
    for program in programs:
        participants = Contestant.objects.filter(
            participation__program=program
        ).select_related('team', 'category').order_by('chest_no')

        # Filter by team if user is team-based
        if hasattr(user, 'team'):
            participants = participants.filter(team=user.team)

        program_participants.append({
            'program': program,
            'participants': participants
        })

    # Prepare filename
    if hasattr(user, 'team'):
        filename = f"all_programs_{user.team.name}_call_list.pdf"
    else:
        filename = "all_programs_call_list.pdf"

    # Render template
    template_path = 'all_call_list_pdf.html'  # New template for all programs
    context = {
        'program_participants': program_participants,
        'user': user,
        'is_team_user': hasattr(user, 'team'),
        'team_name': user.team.name if hasattr(user, 'team') else None
    }

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    template = get_template(template_path)
    html = template.render(context)

    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('We had some errors <pre>' + html + '</pre>')
    return response


def chest_number(request):
    contestant = Contestant.objects.all()

    context = {
        'contestant' : contestant
    }
    return render(request, 'chest_number.html', context)

@login_required
def all_green_room_lists(request):
    """Show Green Room List (sign sheet) for ALL programs as HTML"""
    user = request.user

    programs = Program.objects.all().select_related('category').order_by('category__name', 'name')
    program_participants = []

    for program in programs:
        participants = Contestant.objects.filter(
            participation__program=program
        ).select_related('team', 'category').order_by('chest_no')

        # Filter by team if user belongs to a team
        if hasattr(user, 'team'):
            participants = participants.filter(team=user.team)

        program_participants.append({
            'program': program,
            'participants': participants
        })

    context = {
        'program_participants': program_participants,
        'is_team_user': hasattr(user, 'team'),
        'team_name': user.team.name if hasattr(user, 'team') else None
    }
    return render(request, 'all_green_room_list.html', context)

@login_required
def download_all_green_room_pdf(request):
    """Download Green Room Lists for all programs as PDF"""
    user = request.user

    # Fetch programs ordered by category, then program name
    programs = Program.objects.all().select_related('category').order_by('category__name', 'name')

    program_participants = []
    for program in programs:
        participants = Contestant.objects.filter(
            participation__program=program
        ).select_related('team', 'category').order_by('chest_no')

        # Filter by team if team user
        if hasattr(user, 'team'):
            participants = participants.filter(team=user.team)

        program_participants.append({
            'program': program,
            'participants': participants
        })

    # Filename
    if hasattr(user, 'team'):
        filename = f"all_green_room_{user.team.name}.pdf"
    else:
        filename = "all_green_room.pdf"

    # Render template
    template_path = 'all_green_room_pdf.html'
    context = {
        'program_participants': program_participants,
        'is_team_user': hasattr(user, 'team'),
        'team_name': user.team.name if hasattr(user, 'team') else None
    }

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    template = get_template(template_path)
    html = template.render(context)

    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('We had some errors <pre>' + html + '</pre>')
    return response



@login_required
def download_all_valuation_forms_pdf(request):
    """Download Valuation Form PDF for ALL programs"""
    user = request.user

    programs = Program.objects.all().order_by('name')
    program_participants = []

    for program in programs:
        participants = Contestant.objects.filter(
            participation__program=program
        ).select_related('team', 'category').order_by('chest_no')

        # Filter by team if user belongs to a team
        if hasattr(user, 'team'):
            participants = participants.filter(team=user.team)

        program_participants.append({
            'program': program,
            'participants': participants
        })

    # File name
    if hasattr(user, 'team'):
        filename = f"all_programs_{user.team.name}_valuation.pdf"
    else:
        filename = "all_programs_valuation.pdf"

    template_path = 'all_valuation_forms.html'  # New template
    context = {
        'program_participants': program_participants,
        'is_team_user': hasattr(user, 'team'),
        'team_name': user.team.name if hasattr(user, 'team') else None
    }

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    template = get_template(template_path)
    html = template.render(context)

    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('We had some errors <pre>' + html + '</pre>')

    return response


from django.http import HttpResponse
from django.template.loader import get_template
from xhtml2pdf import pisa
from .models import Contestant

def download_chest_cards_pdf(request):
    """Download Chest Cards PDF for all contestants"""
    contestants = Contestant.objects.all().order_by('chest_no')

    template_path = 'chest_cards_pdf.html'
    context = {'contestants': contestants}

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="chest_cards.pdf"'

    template = get_template(template_path)
    html = template.render(context)

    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('Error while generating PDF <pre>' + html + '</pre>')
    return response


from django.http import HttpResponse
from django.template.loader import get_template
from xhtml2pdf import pisa
import io

def assigned_programs_pdf(request):
    team_id = request.GET.get('team')
    category_id = request.GET.get('category')

    participations = Participation.objects.all()
    if team_id:
        participations = participations.filter(contestant__team_id=team_id)
    if category_id:
        participations = participations.filter(contestant__category_id=category_id)

    template_path = 'assigned_programs_pdf.html'
    context = {
        'participations': participations,
    }

    # Render HTML
    template = get_template(template_path)
    html = template.render(context)

    # Create PDF
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="assigned_programs.pdf"'
    pisa.CreatePDF(io.BytesIO(html.encode("UTF-8")), dest=response, encoding='UTF-8')

    return response


from django.contrib import messages
from django.db.models import Q
from django.db import transaction
from .models import (
    Program, Contestant, Team, GroupParticipation, 
    Participation, PointsConfig
)

# ----------------- Group Program Management -----------------

def create_group_participation(request):
    """Create a new group participation"""
    if request.method == 'POST':
        program_id = request.POST.get('program_id')
        contestant_ids = request.POST.getlist('contestants')
        group_name = request.POST.get('group_name', '')
        
        try:
            with transaction.atomic():
                program = get_object_or_404(Program, id=program_id, is_group=True)
                
                # Validate contestant count
                if len(contestant_ids) < program.min_participants or len(contestant_ids) > program.max_participants:
                    messages.error(request, 
                        f"Number of participants must be between {program.min_participants} "
                        f"and {program.max_participants}")
                    return redirect('group_participation_form')
                
                # Get contestants and validate they're from the same team
                contestants = Contestant.objects.filter(id__in=contestant_ids)
                teams = set(c.team for c in contestants)
                
                if len(teams) > 1:
                    messages.error(request, "All contestants must be from the same team")
                    return redirect('group_participation_form')
                
                team = list(teams)[0]
                
                # Check if this team already has a group for this program
                existing_group = GroupParticipation.objects.filter(
                    program=program, team=team
                ).first()
                
                if existing_group:
                    messages.error(request, f"Team {team.name} already has a group for {program.name}")
                    return redirect('group_participation_form')
                
                # Create group participation
                group_participation = GroupParticipation.objects.create(
                    program=program,
                    team=team,
                    group_name=group_name
                )
                group_participation.contestants.set(contestants)
                
                messages.success(request, f"Group created successfully for {program.name}")
                return redirect('group_participation_list')
                
        except Exception as e:
            messages.error(request, f"Error creating group: {str(e)}")
            return redirect('group_participation_form')
    
    # GET request - show form
    programs = Program.objects.filter(is_group=True)
    teams = Team.objects.all()
    contestants = Contestant.objects.all().select_related('team')
    
    context = {
        'programs': programs,
        'teams': teams,
        'contestants': contestants,
    }
    return render(request, 'group_participation_form.html', context)

def group_participation_list(request):
    """List all group participations"""
    group_participations = GroupParticipation.objects.all().select_related(
        'program', 'team'
    ).prefetch_related('contestants')
    
    context = {
        'group_participations': group_participations
    }
    return render(request, 'group_participation_list.html', context)

def add_group_marks(request, group_id):
    """Add marks to a group participation"""
    group_participation = get_object_or_404(GroupParticipation, id=group_id)
    
    if request.method == 'POST':
        marks = request.POST.get('marks')
        
        try:
            marks = int(marks)
            if marks < 0 or marks > 100:
                messages.error(request, "Marks must be between 0 and 100")
                return redirect('add_group_marks', group_id=group_id)
            
            group_participation.marks = marks
            group_participation.save()
            
            # Calculate grade
            calculate_group_grades_and_points()
            
            messages.success(request, f"Marks added successfully for {group_participation}")
            return redirect('group_participation_list')
            
        except ValueError:
            messages.error(request, "Please enter valid marks")
            return redirect('add_group_marks', group_id=group_id)
    
    context = {
        'group_participation': group_participation
    }
    return render(request, 'add_group_marks.html', context)

# ----------------- Points Calculation Functions -----------------

def calculate_group_grades_and_points():
    """Calculate grades, ranks, and points for all group participations"""
    config = PointsConfig.get_config()
    
    # Get all programs that have group participations with marks
    programs_with_groups = Program.objects.filter(
        groupparticipation__marks__isnull=False,
        is_group=True
    ).distinct()
    
    for program in programs_with_groups:
        # Get all group participations for this program with marks
        group_participations = GroupParticipation.objects.filter(
            program=program,
            marks__isnull=False
        ).order_by('-marks')  # Order by marks descending
        
        # Calculate ranks
        current_rank = 1
        previous_marks = None
        rank_increment = 1
        
        for i, group in enumerate(group_participations):
            if previous_marks is not None and group.marks < previous_marks:
                current_rank += rank_increment
                rank_increment = 1
            elif previous_marks is not None and group.marks == previous_marks:
                rank_increment += 1
            
            group.rank = current_rank
            previous_marks = group.marks
            
            # Calculate grade based on marks
            if group.marks >= config.grade_a_threshold:
                group.grade = 'A'
            elif group.marks >= config.grade_b_threshold:
                group.grade = 'B'
            elif group.marks >= config.grade_c_threshold:
                group.grade = 'C'
            else:
                group.grade = 'D'
            
            group.save()
    
    # Calculate and award points
    award_group_points()

def award_group_points():
    """Award points to teams based on group participations"""
    config = PointsConfig.get_config()
    
    # Reset points_awarded flag for recalculation
    GroupParticipation.objects.filter(points_awarded=True).update(points_awarded=False)
    
    group_participations = GroupParticipation.objects.filter(
        marks__isnull=False,
        points_awarded=False
    )
    
    for group in group_participations:
        points = 0
        
        # Rank-based points
        if group.rank == 1:
            points += config.rank_1_points
        elif group.rank == 2:
            points += config.rank_2_points
        elif group.rank == 3:
            points += config.rank_3_points
        
        # Grade-based points
        if group.grade == 'A':
            points += config.grade_a_points
        elif group.grade == 'B':
            points += config.grade_b_points
        elif group.grade == 'C':
            points += config.grade_c_points
        
        # Add points to team
        if points > 0:
            group.team.total_points += points
            group.team.save()
            
            # Mark as points awarded
            group.points_awarded = True
            group.save()

def recalculate_all_team_points():
    """Recalculate total points for all teams (both individual and group)"""
    # Reset all team points
    Team.objects.update(total_points=0)
    
    # Reset points awarded flags
    Participation.objects.update(points_awarded=False)
    GroupParticipation.objects.update(points_awarded=False)
    
    # Recalculate individual participations
    calculate_individual_grades_and_points()  # You need to implement this
    
    # Recalculate group participations
    calculate_group_grades_and_points()

def calculate_individual_grades_and_points():
    """Calculate grades, ranks, and points for individual participations"""
    # This is your existing function for individual programs
    # You should implement this similar to group calculation
    config = PointsConfig.get_config()
    
    programs_with_individual = Program.objects.filter(
        participation__marks__isnull=False,
        is_group=False
    ).distinct()
    
    for program in programs_with_individual:
        participations = Participation.objects.filter(
            program=program,
            marks__isnull=False
        ).order_by('-marks')
        
        # Similar ranking logic as group
        current_rank = 1
        previous_marks = None
        rank_increment = 1
        
        for i, participation in enumerate(participations):
            if previous_marks is not None and participation.marks < previous_marks:
                current_rank += rank_increment
                rank_increment = 1
            elif previous_marks is not None and participation.marks == previous_marks:
                rank_increment += 1
            
            participation.rank = current_rank
            previous_marks = participation.marks
            
            # Calculate grade
            if participation.marks >= config.grade_a_threshold:
                participation.grade = 'A'
            elif participation.marks >= config.grade_b_threshold:
                participation.grade = 'B'
            elif participation.marks >= config.grade_c_threshold:
                participation.grade = 'C'
            else:
                participation.grade = 'D'
            
            participation.save()
    
    # Award individual points
    award_individual_points()

def award_individual_points():
    """Award points to teams based on individual participations"""
    config = PointsConfig.get_config()
    
    participations = Participation.objects.filter(
        marks__isnull=False,
        points_awarded=False
    )
    
    for participation in participations:
        points = 0
        
        # Rank-based points
        if participation.rank == 1:
            points += config.rank_1_points
        elif participation.rank == 2:
            points += config.rank_2_points
        elif participation.rank == 3:
            points += config.rank_3_points
        
        # Grade-based points
        if participation.grade == 'A':
            points += config.grade_a_points
        elif participation.grade == 'B':
            points += config.grade_b_points
        elif participation.grade == 'C':
            points += config.grade_c_points
        
        # Add points to contestant's team
        if points > 0:
            participation.contestant.team.total_points += points
            participation.contestant.team.save()
            
            # Also add to contestant's individual points
            participation.contestant.total_points += points
            participation.contestant.save()
            
            # Mark as points awarded
            participation.points_awarded = True
            participation.save()

# ----------------- Leaderboard Views -----------------

def team_leaderboard2(request):
    """Display team leaderboard"""
    teams = Team.objects.all().order_by('-total_points')
    
    context = {
        'teams': teams
    }
    return render(request, 'competition/team_leaderboard.html', context)

def program_results(request, program_id):
    """Display results for a specific program (individual or group)"""
    program = get_object_or_404(Program, id=program_id)
    
    if program.is_group:
        results = GroupParticipation.objects.filter(
            program=program,
            marks__isnull=False
        ).order_by('rank').select_related('team').prefetch_related('contestants')
        template = 'competition/group_program_results.html'
    else:
        results = Participation.objects.filter(
            program=program,
            marks__isnull=False
        ).order_by('rank').select_related('contestant', 'contestant__team')
        template = 'competition/individual_program_results.html'
    
    context = {
        'program': program,
        'results': results
    }
    return render(request, template, context)

# Additional view for recalculating points
def recalculate_points_view(request):
    """Manual recalculation of all points"""
    if request.method == 'POST':
        try:
            from .views import recalculate_all_team_points
            recalculate_all_team_points()
            messages.success(request, "All team points have been recalculated successfully!")
        except Exception as e:
            messages.error(request, f"Error recalculating points: {str(e)}")
    
    return redirect('team_leaderboard')

@login_required
def contestant_points_list(request):
    """Individual contestant points list (JUNIOR and SENIOR only, excluding group programs)"""
    # Only Junior and Senior contestants
    contestants = Contestant.objects.filter(
        category__name__in=["JUNIOR", "SENIOR"]
    ).distinct()

    contestant_results = []

    for contestant in contestants:
        # Exclude group programs and general programs
        participations = Participation.objects.filter(
            contestant=contestant,
            marks__isnull=False
        ).exclude(
            program__is_group=True
        ).exclude(
            program__category__name__iexact="GENERAL"
        ).select_related("program", "program__category")

        total_points = 0
        program_details = []

        for p in participations:
            # Skip if marks are 0 or not awarded
            if not p.points_awarded or not p.marks or p.marks == 0:
                continue

            # Individual programs only (is_group=False), so members_count = 1
            rank_pts, grade_pts, total_pts = calculate_points(
                p.rank, 
                p.grade, 
                is_group=False,  # Always False since we're excluding group programs
                members_count=1
            )

            total_points += total_pts

            program_details.append({
                "program_name": p.program.name,
                "program_category": p.program.category.name,
                "rank": p.rank,
                "grade": p.grade,
                "marks": p.marks,
                "rank_points": rank_pts,
                "grade_points": grade_pts,
                "total_points": total_pts
            })

        if program_details:
            contestant_results.append({
                "contestant": contestant,
                "programs": program_details,
                "total_points": total_points,
                "program_count": len(program_details)
            })

    # Sort by total points descending
    contestant_results.sort(key=lambda x: x["total_points"], reverse=True)

    # Add positions
    for i, cr in enumerate(contestant_results, 1):
        cr['position'] = i

    return render(request, "contestant_points.html", {
        "contestant_results": contestant_results,
        "total_contestants": len(contestant_results)
    })


def results_page(request):
    return render (request, 'results_page.html')

from django.shortcuts import render
from .models import Contestant, Category, Program

@login_required
def contestant_programs(request):
    """View contestant programs with team and category filters"""
    is_team_user = request.user.role == 'team'
    
    # Get filter parameters
    team_id = request.GET.get('team')
    category_id = request.GET.get('category')
    
    # Base queryset
    if is_team_user:
        contestants = Contestant.objects.filter(team=request.user.team)
        team_name = request.user.team.name
        teams = None  # Team users don't need team filter
    else:
        contestants = Contestant.objects.all()
        team_name = None
        teams = Team.objects.all().order_by('name')
    
    # Apply filters
    if team_id:
        contestants = contestants.filter(team_id=team_id)
        selected_team = Team.objects.get(id=team_id) if team_id else None
    else:
        selected_team = None
    
    if category_id:
        contestants = contestants.filter(category_id=category_id)
        selected_category = Category.objects.get(id=category_id) if category_id else None
    else:
        selected_category = None
    
    # Get all categories for filter
    categories = Category.objects.all().order_by('name')
    
    # Prefetch related data for efficiency
    contestants = contestants.select_related(
        'team', 'category'
    ).prefetch_related(
        'participation_set__program__category'
    ).order_by('chest_no')
    
    context = {
        'contestants': contestants,
        'is_team_user': is_team_user,
        'team_name': team_name,
        'teams': teams,
        'categories': categories,
        'selected_team': selected_team,
        'selected_category': selected_category,
        'team_id': team_id,
        'category_id': category_id,
    }
    
    return render(request, 'contestant_programs.html', context)


@login_required
def contestant_programs_pdf(request):
    """Generate PDF of contestant programs with filters"""
    from django.http import HttpResponse
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from io import BytesIO
    
    is_team_user = request.user.role == 'team'
    team_id = request.GET.get('team')
    category_id = request.GET.get('category')
    
    # Get filtered contestants
    if is_team_user:
        contestants = Contestant.objects.filter(team=request.user.team)
        team_name = request.user.team.name
    else:
        contestants = Contestant.objects.all()
        team_name = None
    
    if team_id:
        contestants = contestants.filter(team_id=team_id)
        team_name = Team.objects.get(id=team_id).name
    
    if category_id:
        contestants = contestants.filter(category_id=category_id)
        category_name = Category.objects.get(id=category_id).name
    else:
        category_name = "All Categories"
    
    contestants = contestants.select_related(
        'team', 'category'
    ).prefetch_related(
        'participation_set__program__category'
    ).order_by('chest_no')
    
    # Create PDF
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=0.5*inch, bottomMargin=0.5*inch)
    elements = []
    styles = getSampleStyleSheet()
    
    # Title style
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=colors.HexColor('#1a1a1a'),
        spaceAfter=30,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold'
    )
    
    # Subtitle style
    subtitle_style = ParagraphStyle(
        'Subtitle',
        parent=styles['Normal'],
        fontSize=12,
        textColor=colors.HexColor('#666666'),
        spaceAfter=20,
        alignment=TA_CENTER,
    )
    
    # Add title
    title = Paragraph("🎭 Contestant Programs", title_style)
    elements.append(title)
    
    # Add filter info
    filter_info = []
    if team_name:
        filter_info.append(f"Team: {team_name}")
    if category_name != "All Categories":
        filter_info.append(f"Category: {category_name}")
    
    if filter_info:
        subtitle = Paragraph(" | ".join(filter_info), subtitle_style)
        elements.append(subtitle)
    
    elements.append(Spacer(1, 0.3*inch))
    
    # Process each contestant
    for idx, contestant in enumerate(contestants, 1):
        # Contestant header data
        data = [
            ['#', 'Name', 'Chest No', 'Team', 'Category'],
            [
                str(idx),
                contestant.name.upper(),
                str(contestant.chest_no),
                contestant.team.name,
                contestant.category.name
            ]
        ]
        
        # Create contestant info table
        t = Table(data, colWidths=[0.5*inch, 2.5*inch, 1*inch, 1.5*inch, 1.5*inch])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#ecf0f1')),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#bdc3c7')),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('TOPPADDING', (0, 1), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 0.1*inch))
        
        # Programs table
        participations = contestant.participation_set.all()
        if participations:
            program_data = [['Program Name', 'Program Category', 'Type']]
            
            for p in participations:
                program_type = "Group" if p.program.is_group else "Individual"
                program_data.append([
                    p.program.name,
                    p.program.category.name,
                    program_type
                ])
            
            program_table = Table(program_data, colWidths=[3.5*inch, 2*inch, 1.5*inch])
            program_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498db')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 9),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
                ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('FONTSIZE', (0, 1), (-1, -1), 8),
                ('TOPPADDING', (0, 1), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            elements.append(program_table)
        else:
            no_programs = Paragraph("<i>No programs assigned</i>", styles['Italic'])
            elements.append(no_programs)
        
        elements.append(Spacer(1, 0.3*inch))
        
        # Add page break after every 3 contestants (except last)
        if idx % 3 == 0 and idx < len(contestants):
            elements.append(PageBreak())
    
    # Build PDF
    doc.build(elements)
    
    # Get PDF value and return response
    pdf = buffer.getvalue()
    buffer.close()
    
    response = HttpResponse(content_type='application/pdf')
    filename = f"contestant_programs"
    if team_name:
        filename += f"_{team_name.replace(' ', '_')}"
    if category_name != "All Categories":
        filename += f"_{category_name.replace(' ', '_')}"
    filename += ".pdf"
    
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response.write(pdf)
    
    return response

@login_required
def contestant_programs_pdf_xml(request):
    """
    Generate PDF using xhtml2pdf (pisa).
    Team users see only their team's contestants.
    """
    user = request.user
    is_team_user = hasattr(user, "team")

    if is_team_user:
        contestants = Contestant.objects.filter(team=user.team).prefetch_related(
            "participation_set__program__category"
        )
        team_name = user.team.name
    else:
        contestants = Contestant.objects.all().prefetch_related(
            "participation_set__program__category"
        )
        team_name = None

    context = {
        "contestants": contestants,
        "is_team_user": is_team_user,
        "team_name": team_name,
    }

    # Render HTML template to string
    template = get_template("contestant_programs_pdf_xml.html")
    html = template.render(context)

    # Create PDF
    result = io.BytesIO()
    pisa_status = pisa.CreatePDF(src=html, dest=result, encoding='utf-8')

    if pisa_status.err:
        # For debug you can return html, but in production give a friendly message
        return HttpResponse('We had some errors while generating PDF. Please check your template and CSS.')

    # Return PDF as response
    response = HttpResponse(result.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="contestant_programs.pdf"'
    return response

@login_required
def enter_marks_summary_cat(request):
    if request.user.role != 'admin':
        return redirect('dashboard_team')

    # Get filter parameters
    program_id = request.GET.get('program')
    category_id = request.GET.get('category')

    # Get all programs and categories for filter dropdowns
    programs = Program.objects.all().order_by('name')
    categories = Category.objects.all().order_by('name')

    # Base queryset
    participations = Participation.objects.filter(marks__isnull=False)

    # Apply filters
    if program_id:
        participations = participations.filter(program_id=program_id)
    if category_id:
        participations = participations.filter(contestant__category_id=category_id)

    # Optimize query
    participations = participations.select_related(
        'contestant__team', 'contestant__category', 'program'
    ).order_by('program__name', '-marks')

    # Handle selected objects
    selected_program = Program.objects.get(id=program_id) if program_id else None
    selected_category = Category.objects.get(id=category_id) if category_id else None

    # Ranking + grade assignment logic (same as before) ...
    # You can reuse your ranking & points awarding logic here

    return render(request, 'enter_marks_summary_cat.html', {
        'participations': participations,
        'programs': programs,
        'categories': categories,
        'selected_program': selected_program,
        'selected_category': selected_category,
        'program_id': program_id,
        'category_id': category_id,
    })

from django.shortcuts import render, redirect
from django.db.models import Sum

from django.shortcuts import render, redirect
from django.db.models import Sum

@login_required
def leaderboard_cat(request):
    """Public leaderboard view with category-wise filtering"""
    category_id = request.GET.get('category')
    categories = Category.objects.all().order_by('name')
    teams = Team.objects.all().order_by('name')

    team_data = []

    for team in teams:
        participations = Participation.objects.filter(contestant__team=team)

        # Apply category filter if selected
        if category_id:
            participations = participations.filter(contestant__category_id=category_id)

        if not participations.exists():
            continue  # skip teams with no entries

        # ✅ Pass category_id to get category-specific points
        total_points = recalculate_team_points(team, category_id)

        awarded = participations.filter(points_awarded=True, marks__isnull=False)

        team_data.append({
            'team': team,
            'points': total_points,
            'total_participations': participations.count(),
            'winners_count': awarded.filter(rank__in=[1, 2, 3]).count(),
        })

    # Sort and assign positions
    team_data.sort(key=lambda x: x['points'], reverse=True)
    for i, data in enumerate(team_data, 1):
        data['position'] = i

    selected_category = Category.objects.filter(id=category_id).first() if category_id else None

    return render(request, 'leaderboard_cat.html', {
        'teams': team_data,
        'categories': categories,
        'selected_category': selected_category,
        'top_three': team_data[:3] if len(team_data) >= 3 else team_data,
    })

