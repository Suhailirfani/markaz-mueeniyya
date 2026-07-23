from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
import pandas as pd
from ..models import Program, Category, Team, Contestant, Participation, GroupParticipation, Stage
from ..forms import ContestantForm, TeamForm

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
def dashboard_admin(request):
    programs = Program.objects.all()
    teams = Team.objects.all()
    from django.contrib.auth import get_user_model
    User = get_user_model()
    pending_users = User.objects.filter(is_approved=False, is_superuser=False).exclude(role='admin')
    from ..models import SystemSetting
    from .scoring import get_top_5_balancing_announcement_suggestions
    group_point_system = SystemSetting.get_setting('group_point_system', 'member_count')
    suggested_announcements = get_top_5_balancing_announcement_suggestions()
    context = {
        'programs': programs,
        'teams': teams,
        'pending_users': pending_users,
        'group_point_system': group_point_system,
        'suggested_announcements': suggested_announcements,
    }
    return render(request, 'dashboard_admin.html', context)

@login_required
def dashboard_team(request):
    if request.user.role != 'team': 
        return redirect('dashboard_admin')
    team = request.user.team
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
def add_category(request):
    if not (request.user.is_superuser or request.user.role == 'admin'):
        return redirect('dashboard_team')

    if request.method == 'POST':
        name = request.POST.get('name').strip()
        if name:
            if Category.objects.filter(name__iexact=name).exists():
                messages.warning(request, f"Category '{name}' already exists.")
            else:
                Category.objects.create(name=name)
                messages.success(request, f"Category '{name}' added successfully.")
                return redirect('add_category')
        else:
            messages.error(request, "Category name cannot be empty.")

    categories = Category.objects.all().order_by('name')
    return render(request, 'add_category.html', {'categories': categories})

@login_required
def edit_category(request, category_id):
    if not (request.user.is_superuser or request.user.role == 'admin'):
        return redirect('dashboard_team')

    category = get_object_or_404(Category, id=category_id)

    if request.method == 'POST':
        new_name = request.POST.get('name').strip()
        if new_name:
            category.name = new_name
            category.save()
            messages.success(request, "Category updated successfully.")
            return redirect('add_category')
        else:
            messages.error(request, "Name can't be empty.")

    return render(request, 'edit_category.html', {'category': category})

@login_required
def delete_category(request, category_id):
    if not (request.user.is_superuser or request.user.role == 'admin'):
        return redirect('dashboard_team')

    category = get_object_or_404(Category, id=category_id)
    category.delete()
    messages.success(request, "Category deleted.")
    return redirect('add_category')

@login_required
def add_program(request):
    if not (request.user.is_superuser or request.user.role == 'admin'):
        return redirect('dashboard_team')

    categories = Category.objects.all()
    stages = Stage.objects.all()
    programs = Program.objects.all().order_by('-id')

    if request.method == 'POST':
        if 'excel_file' in request.FILES:
            excel_file = request.FILES['excel_file']

            try:
                df = pd.read_excel(excel_file)
                for _, row in df.iterrows():
                    name = str(row.get("name", "") or row.get("Program Name", "")).strip()
                    category_name = str(row.get("category", "") or row.get("Category", "")).strip()

                    if name and category_name and name.lower() != 'nan' and category_name.lower() != 'nan':
                        try:
                            category = Category.objects.get(name__iexact=category_name)
                            
                            members_cnt = row.get("members_count") or row.get("Members") or 1
                            try:
                                members_cnt = int(members_cnt)
                            except (ValueError, TypeError):
                                members_cnt = 1

                            ptype = str(row.get("type", "") or row.get("program_type", "") or row.get("Venue Type", "")).strip().upper()
                            ptype_val = "OFF_STAGE" if "OFF" in ptype else "STAGE"

                            pmode = str(row.get("mode", "") or row.get("presentation_mode", "") or row.get("Mode", "")).strip().upper()
                            pmode_val = "SIMULTANEOUS" if any(x in pmode for x in ["SIMULTANEOUS", "ALL", "WRITTEN", "ESSAY"]) else "SEQUENTIAL"

                            dur = row.get("duration") or row.get("duration_per_participant") or row.get("Duration") or 5
                            try:
                                dur = int(dur)
                            except (ValueError, TypeError):
                                dur = 5

                            buf = row.get("buffer") or row.get("buffer_margin_minutes") or row.get("Buffer") or 0
                            try:
                                buf = int(buf)
                            except (ValueError, TypeError):
                                buf = 0

                            pref_stage_name = str(row.get("stage") or row.get("preferred_stage") or row.get("Stage Priority") or "").strip()
                            pref_stage = None
                            if pref_stage_name and pref_stage_name.lower() != 'nan':
                                pref_stage = Stage.objects.filter(name__iexact=pref_stage_name).first()

                            Program.objects.create(
                                name=name,
                                category=category,
                                is_group=(members_cnt > 1),
                                members_count=members_cnt,
                                program_type=ptype_val,
                                presentation_mode=pmode_val,
                                duration_per_participant=dur,
                                buffer_margin_minutes=buf,
                                preferred_stage=pref_stage
                            )
                        except Category.DoesNotExist:
                            messages.warning(request, f"Category '{category_name}' not found for program '{name}'. Skipped.")
                messages.success(request, "Bulk upload completed successfully with schedule settings.")
            except Exception as e:
                messages.error(request, f"Error processing Excel file: {e}")

            return redirect('add_program')

        else:
            name = request.POST.get('name')
            category_id = request.POST.get('category')
            members_count = request.POST.get('members_count', '1')
            program_type = request.POST.get('program_type', 'STAGE')
            presentation_mode = request.POST.get('presentation_mode', 'SEQUENTIAL')
            duration_per_participant = request.POST.get('duration_per_participant', '5')
            buffer_margin_minutes = request.POST.get('buffer_margin_minutes', '0')
            preferred_stage_id = request.POST.get('preferred_stage')

            if name and category_id:
                category = Category.objects.get(id=category_id)
                pref_stage = Stage.objects.filter(id=preferred_stage_id).first() if preferred_stage_id else None
                cnt = int(members_count) if members_count and members_count.isdigit() else 1

                Program.objects.create(
                    name=name,
                    category=category,
                    is_group=(cnt > 1),
                    members_count=cnt,
                    program_type=program_type,
                    presentation_mode=presentation_mode,
                    duration_per_participant=int(duration_per_participant or 5),
                    buffer_margin_minutes=int(buffer_margin_minutes or 0),
                    preferred_stage=pref_stage
                )
                messages.success(request, f"Program '{name}' added successfully under {category.name}.")
                return redirect('add_program')
            else:
                messages.error(request, "All fields are required.")

    return render(request, 'add_program.html', {
        'categories': categories,
        'stages': stages,
        'programs': programs
    })

@login_required
def edit_program(request, program_id):
    if request.user.role != 'admin':
        return redirect('dashboard_team')

    program = get_object_or_404(Program, id=program_id)
    categories = Category.objects.all()
    stages = Stage.objects.all()

    if request.method == 'POST':
        name = request.POST.get('name').strip()
        category_id = request.POST.get('category')
        members_count = request.POST.get('members_count', '1')
        program_type = request.POST.get('program_type', 'STAGE')
        presentation_mode = request.POST.get('presentation_mode', 'SEQUENTIAL')
        duration_per_participant = request.POST.get('duration_per_participant', '5')
        buffer_margin_minutes = request.POST.get('buffer_margin_minutes', '0')
        preferred_stage_id = request.POST.get('preferred_stage')

        if name and category_id:
            category = get_object_or_404(Category, id=category_id)
            cnt = int(members_count) if members_count and members_count.isdigit() else 1

            program.name = name
            program.category = category
            program.is_group = (cnt > 1)
            program.members_count = cnt
            program.program_type = program_type
            program.presentation_mode = presentation_mode
            program.duration_per_participant = int(duration_per_participant or 5)
            program.buffer_margin_minutes = int(buffer_margin_minutes or 0)
            program.preferred_stage = Stage.objects.filter(id=preferred_stage_id).first() if preferred_stage_id else None
            program.save()

            messages.success(request, "Program updated successfully.")
            return redirect('add_program')
        else:
            messages.error(request, "All fields are required.")

    return render(request, 'edit_program.html', {
        'program': program,
        'categories': categories,
        'stages': stages
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
        program_ids = request.POST.getlist("program_ids")
        if program_ids:
            Program.objects.filter(id__in=program_ids).delete()
            messages.success(request, f"{len(program_ids)} programs deleted successfully.")
        else:
            messages.warning(request, "No programs selected.")
        return redirect('add_program')

    programs = Program.objects.all().order_by('name')
    return render(request, "bulk_delete_programs.html", {"programs": programs})

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
def participant_list(request):
    user = request.user
    team_id = request.GET.get('team_id')
    category_id = request.GET.get('category_id')

    teams = Team.objects.all()
    categories = Category.objects.all()
    participants = Contestant.objects.select_related('team', 'category').order_by('chest_no')

    if hasattr(user, 'team'):
        participants = participants.filter(team=user.team)
        team_id = user.team.id
    else:
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
    categories = Category.objects.all().order_by('name')
    participants = Contestant.objects.select_related('team', 'category').order_by('chest_no')

    if hasattr(user, 'team'):
        participants = participants.filter(team=user.team)

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
    teams = Team.objects.all().order_by('name')
    participants = Contestant.objects.select_related('team', 'category').order_by('chest_no')

    if hasattr(user, 'team'):
        teams = Team.objects.filter(id=user.team.id)
        participants = participants.filter(team=user.team)

    participants_by_team = {}
    for team in teams:
        team_participants = participants.filter(team=team)
        if team_participants.exists():
            participants_by_team[team] = team_participants

    return render(request, 'participants_by_team.html', {
        'participants_by_team': participants_by_team,
        'total_participants': participants.count(),
    })

def add_participant(request):
    if request.method == 'POST':
        if 'excel_file' in request.FILES:
            excel_file = request.FILES['excel_file']
            try:
                df = pd.read_excel(excel_file)
                for _, row in df.iterrows():
                    name = row.get("name")
                    team_name = row.get("team")
                    category_name = row.get("category")

                    if not (name and team_name and category_name):
                        continue

                    try:
                        team = Team.objects.get(name=team_name)
                        category = Category.objects.get(name=category_name)
                        Contestant.objects.create(
                            name=name,
                            team=team,
                            category=category,
                        )
                    except Team.DoesNotExist:
                        messages.warning(request, f"Team '{team_name}' not found. Skipped {name}.")
                    except Category.DoesNotExist:
                        messages.warning(request, f"Category '{category_name}' not found. Skipped {name}.")

                messages.success(request, "Bulk participant upload successful.")
            except Exception as e:
                messages.error(request, f"Error processing Excel: {e}")

            return redirect('participant_list')

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
    user_id = request.GET.get('user_id')
    initial = {}
    if user_id:
        initial['user'] = user_id
    form = TeamForm(request.POST or None, initial=initial)
    if form.is_valid():
        form.save()
        messages.success(request, "Team created and assigned successfully!")
        if user_id:
            return redirect('pending_users')
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

@login_required
def assign_programs(request):
    is_team_user = request.user.role == 'team' and hasattr(request.user, 'team')
    if is_team_user:
        teams = Team.objects.filter(id=request.user.team.id)
        team_id = str(request.user.team.id)
    else:
        teams = Team.objects.all()
        team_id = request.GET.get('team')

    categories = Category.objects.all()

    contestants = Contestant.objects.none()
    programs = Program.objects.none()

    category_id = request.GET.get('category')

    if team_id and category_id:
        try:
            selected_category = Category.objects.get(id=category_id)

            if selected_category.name.upper() == "GENERAL":
                contestants = Contestant.objects.filter(
                    team_id=team_id,
                    category__name__in=["APEX", "VERTEX", "CORTEX"]
                )
                programs = Program.objects.filter(category=selected_category)

            elif selected_category.name.upper() == "CATEGORY A":
                contestants = Contestant.objects.filter(
                    team_id=team_id,
                    category__name__in=["APEX", "VERTEX"]
                )
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

        # Security check: contestant must belong to team leader's team
        if is_team_user:
            contestant = get_object_or_404(Contestant, id=contestant_id, team=request.user.team)
        else:
            contestant = get_object_or_404(Contestant, id=contestant_id)

        if len(selected_programs) > 5:
            messages.error(request, "You can only select up to 5 programs.")
        else:
            for prog_id in selected_programs:
                Participation.objects.get_or_create(
                    contestant=contestant,
                    program_id=prog_id
                )
            messages.success(request, "Programs assigned successfully!")
            return redirect('assign_programs')

    return render(request, 'assign_programs.html', {
        'teams': teams,
        'categories': categories,
        'contestants': contestants,
        'programs': programs,
        'is_team_user': is_team_user,
    })

def view_assigned_programs(request):
    is_team_user = request.user.role == 'team' and hasattr(request.user, 'team')
    category_id = request.GET.get('category')

    participations = Participation.objects.select_related(
        'contestant__team', 'contestant__category', 'program'
    )

    if is_team_user:
        team_id = request.user.team.id
        teams = Team.objects.filter(id=team_id)
        participations = participations.filter(contestant__team_id=team_id)
    else:
        team_id = request.GET.get('team')
        teams = Team.objects.all()
        if team_id:
            participations = participations.filter(contestant__team_id=team_id)

    if category_id:
        participations = participations.filter(contestant__category_id=category_id)

    context = {
        'participations': participations.order_by('contestant__team__name'),
        'teams': teams,
        'categories': Category.objects.all(),
        'selected_team': int(team_id) if team_id else '',
        'selected_category': int(category_id) if category_id else '',
        'is_team_user': is_team_user,
    }

    return render(request, 'assigned_programs.html', context)

@login_required
def edit_assigned_programs(request, contestant_id):
    if request.user.role == 'team' and hasattr(request.user, 'team'):
        contestant = get_object_or_404(Contestant, id=contestant_id, team=request.user.team)
    else:
        contestant = get_object_or_404(Contestant, id=contestant_id)

    all_programs = Program.objects.filter(
        Q(category=contestant.category) | Q(category__name="GENERAL")
    )

    assigned_programs = Participation.objects.filter(contestant=contestant).values_list('program_id', flat=True)

    if request.method == "POST":
        selected_program_ids = request.POST.getlist('programs')

        Participation.objects.filter(contestant=contestant).delete()

        for program_id in selected_program_ids:
            Participation.objects.create(contestant=contestant, program_id=program_id)

        messages.success(request, "Programs updated successfully.")
        return redirect("assigned_programs")

    return render(request, "edit_assigned_programs.html", {
        "contestant": contestant,
        "all_programs": all_programs,
        "assigned_program_ids": list(assigned_programs),
    })

@login_required
def delete_assigned_program(request, participation_id):
    if request.user.role == 'team' and hasattr(request.user, 'team'):
        participation = get_object_or_404(Participation, id=participation_id, contestant__team=request.user.team)
    else:
        participation = get_object_or_404(Participation, id=participation_id)
    participation.delete()
    messages.success(request, "Program assignment removed successfully.")
    return redirect('assigned_programs')

def program_list(request):
    programs = Program.objects.all().order_by('category__name', 'name')
    categories = Category.objects.all()

    context = {
        'programs':programs,
        'categories': categories
    }
    return render(request, 'program_list.html', context)

@login_required
def contestant_programs(request):
    user = request.user

    if hasattr(user, "team"):
        contestants = Contestant.objects.filter(team=user.team).prefetch_related(
            "participation_set__program__category"
        )
        is_team_user = True
        team_name = user.team.name
    else:
        contestants = Contestant.objects.prefetch_related(
            "participation_set__program__category"
        )
        is_team_user = False
        team_name = None

    context = {
        "contestants": contestants,
        "is_team_user": is_team_user,
        "team_name": team_name,
    }
    return render(request, "contestant_programs.html", context)

@login_required
def program_participants(request):
    user = request.user
    program_id = request.GET.get('program_id')

    programs = Program.objects.all().order_by('name')
    participants = None
    selected_program = None

    if program_id:
        try:
            selected_program = Program.objects.get(id=program_id)
            participants = Contestant.objects.filter(
                program=selected_program
            ).select_related('team', 'category').order_by('chest_no')

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
def green_room_list(request, program_id):
    try:
        program = Program.objects.get(id=program_id)
    except Program.DoesNotExist:
        return HttpResponse('Program not found', status=404)

    user = request.user
    participants = Contestant.objects.filter(
        participation__program=program
    ).select_related('team', 'category').order_by('chest_no')

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
def all_green_room_lists(request):
    user = request.user

    programs = Program.objects.all().select_related('category').order_by('category__name', 'name')
    program_participants = []

    for program in programs:
        participants = Contestant.objects.filter(
            participation__program=program
        ).select_related('team', 'category').order_by('chest_no')

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

def list_page(request):
    return render(request, 'list_page.html')

def get_programs_for_contestant(request):
    contestant_id = request.GET.get('contestant_id')
    category_id = request.GET.get('category_id')

    if not contestant_id or not category_id:
        return JsonResponse({'programs': []})

    # Get programs of selected category not already assigned
    assigned_programs = Participation.objects.filter(
        contestant_id=contestant_id
    ).values_list('program_id', flat=True)

    programs = Program.objects.filter(
        category_id=category_id
    ).exclude(id__in=assigned_programs)

    return JsonResponse({
        'programs': list(programs.values('id', 'name'))
    })

def get_contestants(request):
    team_id = request.GET.get('team_id')
    category_id = request.GET.get('category_id')

    contestants = Contestant.objects.filter(
        team_id=team_id, category_id=category_id
    ).values('id', 'name')

    return JsonResponse({'contestants': list(contestants)})

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
        group_name = request.POST.get('group_name', '').strip()

        program = get_object_or_404(Program, id=program_id)
        required_cnt = program.members_count or 1

        if len(participant_ids) != required_cnt:
            messages.error(request, f"Please select exactly {required_cnt} participants for {program.name}.")
            return redirect('assign_group_program')

        contestants = Contestant.objects.filter(id__in=participant_ids)
        teams = set(c.team for c in contestants if c.team)

        if not teams:
            messages.error(request, "Participants must belong to a team.")
            return redirect('assign_group_program')

        if len(teams) > 1:
            messages.error(request, "All group participants must belong to the same team.")
            return redirect('assign_group_program')

        team = list(teams)[0]
        existing_cnt = GroupParticipation.objects.filter(program=program, team=team).count()

        if not group_name:
            group_name = f"{team.name} - Group {existing_cnt + 1}"

        group_participation = GroupParticipation.objects.create(
            program=program,
            team=team,
            group_name=group_name
        )
        group_participation.contestants.set(contestants) 

        messages.success(request, f"Group '{group_name}' assigned successfully with {len(contestants)} members.")
        return redirect('assign_group_program')

    return render(request, 'assign_group_program.html', {'categories': categories})

@login_required
@csrf_exempt
def get_group_programs(request):
    category_id = request.POST.get('category_id')
    programs = Program.objects.filter(category_id=category_id, is_group=True)
    program_list = [{"id": p.id, "name": p.name, "members_count": p.members_count or 1} for p in programs]
    return JsonResponse({"programs": program_list})

@login_required
@csrf_exempt
def get_participants_by_category(request):
    category_id = request.POST.get('category_id')
    contestants = Contestant.objects.filter(category_id=category_id)
    contestant_list = [{"id": c.id, "name": c.name} for c in contestants]
    return JsonResponse({"contestants": contestant_list})

@login_required
def chest_number(request):
    """View, manage, and auto-distribute chest numbers for contestants"""
    if request.user.role != 'admin':
        messages.error(request, 'Permission denied.')
        return redirect('dashboard_admin')

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'distribute':
            try:
                start_no = int(request.POST.get('start_no', 101))
            except ValueError:
                start_no = 101

            order_by = request.POST.get('order_by', 'category')

            if order_by == 'category':
                contestants = Contestant.objects.select_related('category', 'team').order_by('category__name', 'name')
            elif order_by == 'team':
                contestants = Contestant.objects.select_related('category', 'team').order_by('team__name', 'name')
            else:
                contestants = Contestant.objects.select_related('category', 'team').order_by('name')

            current_no = start_no
            for c in contestants:
                c.chest_no = current_no
                c.save()
                current_no += 1

            messages.success(request, f"Chest numbers successfully assigned to {contestants.count()} contestants starting from #{start_no}.")
            return redirect('chest_number')

    category_id = request.GET.get('category')
    team_id = request.GET.get('team')
    query = request.GET.get('q', '').strip()

    contestants = Contestant.objects.select_related('category', 'team').order_by('chest_no', 'id')

    if category_id:
        contestants = contestants.filter(category_id=category_id)
    if team_id:
        contestants = contestants.filter(team_id=team_id)
    if query:
        contestants = contestants.filter(
            Q(name__icontains=query) | Q(chest_no__icontains=query)
        )

    categories = Category.objects.all()
    teams = Team.objects.all()

    context = {
        'contestant': contestants,
        'categories': categories,
        'teams': teams,
        'selected_category': category_id,
        'selected_team': team_id,
        'search_query': query,
        'total_count': Contestant.objects.count(),
        'assigned_count': Contestant.objects.filter(chest_no__isnull=False).count(),
    }
    return render(request, 'chest_number.html', context)



@login_required
def download_program_excel_template(request):
    """
    Generates and downloads a clean Excel template (.xlsx) with sample program rows
    and scheduling columns (name, category, members_count, type, mode, duration, buffer, stage).
    """
    sample_data = [
        {
            'name': 'Qur-an Recitation',
            'category': 'SENIOR',
            'members_count': 1,
            'type': 'Stage',
            'mode': 'Sequential',
            'duration': 5,
            'buffer': 0,
            'stage': 'Stage 1'
        },
        {
            'name': 'Elocution / Speech',
            'category': 'JUNIOR',
            'members_count': 1,
            'type': 'Stage',
            'mode': 'Sequential',
            'duration': 6,
            'buffer': 1,
            'stage': 'Stage 2'
        },
        {
            'name': 'Essay Writing',
            'category': 'SENIOR',
            'members_count': 1,
            'type': 'Off-Stage',
            'mode': 'Simultaneous',
            'duration': 40,
            'buffer': 5,
            'stage': 'Stage 4'
        },
        {
            'name': 'Pencil Drawing',
            'category': 'SUBJUNIOR',
            'members_count': 1,
            'type': 'Off-Stage',
            'mode': 'Simultaneous',
            'duration': 30,
            'buffer': 0,
            'stage': 'Stage 4'
        },
        {
            'name': 'Duffmuttu (Group)',
            'category': 'SENIOR',
            'members_count': 7,
            'type': 'Stage',
            'mode': 'Sequential',
            'duration': 10,
            'buffer': 2,
            'stage': 'Stage 1'
        }
    ]

    df = pd.DataFrame(sample_data)

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename="Program_Import_Template.xlsx"'

    with pd.ExcelWriter(response, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Program Templates')
        
        cat_names = list(Category.objects.values_list('name', flat=True))
        stage_names = list(Stage.objects.values_list('name', flat=True))

        max_len = max(len(cat_names), len(stage_names), 1)
        cat_names += [''] * (max_len - len(cat_names))
        stage_names += [''] * (max_len - len(stage_names))

        ref_df = pd.DataFrame({
            'Available Categories': cat_names,
            'Available Stages / Venues': stage_names
        })
        ref_df.to_excel(writer, index=False, sheet_name='Reference Guide')

    return response



