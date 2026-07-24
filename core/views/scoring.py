from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.http import JsonResponse
from django.forms import modelformset_factory
from ..models import Program, Category, Team, Contestant, Participation, TeamPoints, SystemSetting, GroupParticipation, PointsConfig
from ..forms import MarkEntryForm
from ..utils import POINTS_FOR_RANK, POINTS_FOR_GRADE

# Individual Program Points Constants
INDIVIDUAL_RANK_POINTS = {1: 3, 2: 2, 3: 1}
INDIVIDUAL_GRADE_POINTS = {'A+': 6, 'A': 5, 'B': 3, 'C': 1}

# Grade thresholds
GRADE_THRESHOLDS = [
    (90, 'A+'),
    (70, 'A'),
    (60, 'B'),
    (50, 'C'),
]

def get_grade(marks):
    """Convert marks to grade based on thresholds"""
    if marks is None:
        return None
    for threshold, grade in GRADE_THRESHOLDS:
        if marks >= threshold:
            return grade
    return None

def get_members_count_for_program(program):
    """Get members count for a program - defaults to 1 if not set"""
    return getattr(program, 'members_count', 1) or 1

def calculate_group_rank_points(rank, members_count):
    """Calculate rank points for group programs based on members count or fixed setting"""
    system_val = SystemSetting.get_setting('group_point_system', 'member_count')
    if system_val == 'fixed':
        fixed_points = {1: 10, 2: 6, 3: 3}
        return fixed_points.get(rank, 0)
    else:
        multipliers = {1: 3, 2: 2, 3: 1}
        return multipliers.get(rank, 0) * members_count

def calculate_points(rank, grade, is_group=False, members_count=1):
    """Calculate total points based on rank and grade"""
    rank_points = 0
    if rank and rank <= 3:
        if is_group:
            rank_points = calculate_group_rank_points(rank, members_count)
        else:
            rank_points = INDIVIDUAL_RANK_POINTS.get(rank, 0)

    grade_points = INDIVIDUAL_GRADE_POINTS.get(grade, 0) if grade else 0

    return rank_points, grade_points, rank_points + grade_points

def assign_ranks_with_ties(participations):
    """Assign ranks handling ties properly - skip zero marks"""
    if not participations:
        return

    current_rank = 1
    prev_marks = None
    skip_count = 0

    for participant in participations:
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

def recalculate_team_points(team, announced_only=False):
    """Recalculate total points for a team from scratch"""
    participations = Participation.objects.filter(
        contestant__team=team,
        points_awarded=True,
        marks__isnull=False
    ).select_related('program', 'contestant__category')

    if announced_only:
        participations = participations.filter(program__is_announced=True)

    total_points = 0
    for p in participations:
        is_group = p.program.is_group
        members_count = get_members_count_for_program(p.program) if is_group else 1
        _, _, points = calculate_points(p.rank, p.grade, is_group, members_count)
        total_points += points

    # Save to the DB only when calculating overall real points (to keep standard fields consistent)
    if not announced_only:
        team_points, _ = TeamPoints.objects.get_or_create(team=team)
        team_points.points = total_points
        team_points.save()

    return total_points

@login_required
def enter_marks_summary(request):
    """Admin view to see marks summary and award points"""
    if request.user.role != 'admin':
        return redirect('dashboard_team')

    program_id = request.GET.get('program')
    programs = Program.objects.all().order_by('name')

    if program_id:
        participations = Participation.objects.filter(
            marks__isnull=False,
            program_id=program_id
        ).select_related('contestant__team', 'contestant__category', 'program').order_by('-marks')
        selected_program = get_object_or_404(Program, id=program_id)

        calculate_and_award_points_for_program(selected_program)
    else:
        participations = Participation.objects.filter(
            marks__isnull=False
        ).select_related('contestant__team', 'contestant__category', 'program').order_by('program__name', '-marks')
        selected_program = None

        for program in Program.objects.all():
            calculate_and_award_points_for_program(program)

    for p in participations:
        members_count = get_members_count_for_program(p.program) if p.program.is_group else 1
        rank_pts, grade_pts, total_pts = calculate_points(
            p.rank, p.grade, p.program.is_group, members_count
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

    assign_ranks_with_ties(participations)

    members_count = get_members_count_for_program(program) if program.is_group else 1

    for p in participations:
        if p.marks is None or p.marks == 0:
            p.rank = None
            p.grade = None
            p.points_awarded = False
            p.save()
            continue

        p.grade = get_grade(p.marks)

        if not p.points_awarded:
            rank_pts, grade_pts, total_points = calculate_points(
                p.rank, p.grade, program.is_group, members_count
            )

            if total_points > 0:
                award_points_to_team(p, total_points)

        p.save()

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

    for p in participations:
        members_count = get_members_count_for_program(p.program) if p.program.is_group else 1
        rank_pts, grade_pts, total_pts = calculate_points(
            p.rank, p.grade, p.program.is_group, members_count
        )
        p.rank_points = rank_pts
        p.grade_points = grade_pts
        p.total_points = total_pts if p.points_awarded else 0

    return render(request, 'team_marks_summary.html', {
        'team': team,
        'participations': participations,
    })

@login_required
def results_view(request):
    """View all results"""
    is_admin = request.user.is_authenticated and request.user.role == 'admin'
    view_mode = request.GET.get('view', 'announced') if is_admin else 'announced'
    announced_only = (view_mode == 'announced')

    participations = Participation.objects.filter(marks__isnull=False)
    if announced_only:
        participations = participations.filter(program__is_announced=True)

    participations = participations.select_related('program', 'contestant', 'contestant__team').order_by('program__name', '-marks')

    return render(request, 'results.html', {
        'participations': participations,
        'is_admin': is_admin,
        'view_mode': view_mode,
        'announced_only': announced_only,
    })

def leaderboard(request):
    """Public leaderboard view with accurate recalculated points"""
    is_admin = request.user.is_authenticated and request.user.role == 'admin'
    view_mode = request.GET.get('view', 'announced') if is_admin else 'announced'
    announced_only = (view_mode == 'announced')

    teams = Team.objects.all().order_by('name')

    team_data = []
    for team in teams:
        total_points = recalculate_team_points(team, announced_only=announced_only)

        participations = Participation.objects.filter(contestant__team=team)
        if announced_only:
            participations = participations.filter(program__is_announced=True)
            
        awarded = participations.filter(points_awarded=True, marks__isnull=False)

        team_data.append({
            'team': team,
            'points': total_points,
            'total_participations': participations.count(),
            'winners_count': awarded.filter(rank__in=[1, 2, 3]).count(),
        })

    team_data.sort(key=lambda x: x['points'], reverse=True)

    current_rank = 1
    for i, data in enumerate(team_data):
        if i > 0 and data['points'] < team_data[i-1]['points']:
            current_rank = i + 1
        data['position'] = current_rank

    # Count of programs
    programs_query = Program.objects.filter(participation__marks__isnull=False).distinct()
    if announced_only:
        programs_query = programs_query.filter(is_announced=True)
    results_added_count = programs_query.count()

    return render(request, 'leaderboard.html', {
        'teams': team_data,
        'top_three': team_data[:3] if len(team_data) >= 3 else team_data,
        'results_added_count': results_added_count,
        'is_admin': is_admin,
        'view_mode': view_mode,
        'announced_only': announced_only,
    })

@login_required
def add_marks(request):
    """Add or edit marks for participants or group entries"""
    if request.user.role != 'admin':
        messages.error(request, 'You do not have permission to access this page.')
        return redirect('dashboard_team')

    category_id = request.GET.get('category')
    program_id = request.GET.get('program')

    categories = Category.objects.all().order_by('name')
    programs = Program.objects.none()
    participations = Participation.objects.none()
    group_participations = GroupParticipation.objects.none()
    selected_program_obj = None

    if category_id:
        programs = Program.objects.filter(category_id=category_id).order_by('name')

    if program_id:
        selected_program_obj = Program.objects.filter(id=program_id).first()
        if selected_program_obj and selected_program_obj.is_group:
            group_participations = GroupParticipation.objects.filter(
                program_id=program_id
            ).select_related('team', 'program').prefetch_related('contestants')
        else:
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
        if selected_program_obj and selected_program_obj.is_group:
            with transaction.atomic():
                saved_count = 0
                for group in group_participations:
                    marks_val = request.POST.get(f'marks_{group.id}')
                    code_val = request.POST.get(f'code_letter_{group.id}', '').strip()

                    if code_val != (group.code_letter or ''):
                        group.code_letter = code_val
                        group.save()

                    if marks_val is not None and marks_val != '':
                        try:
                            group.marks = int(marks_val)
                            group.save()
                            saved_count += 1
                        except ValueError:
                            pass

                calculate_group_grades_and_points()
                messages.success(request, f'Successfully saved marks for {saved_count} group entries!')
            return redirect(f"{request.path}?category={category_id}&program={program_id}")
        else:
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

                    if program_id:
                        program = Program.objects.get(id=program_id)
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
        'selected_program_obj': selected_program_obj,
        'participations': participations,
        'group_participations': group_participations,
    })

@login_required
def undo_points(request, participation_id):
    """Undo points for a participation"""
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

        is_group = participation.program.is_group
        members_count = get_members_count_for_program(participation.program) if is_group else 1
        rank_pts, grade_pts, total_points = calculate_points(
            participation.rank,
            participation.grade,
            is_group,
            members_count
        )

        team = participation.contestant.team
        team_points, _ = TeamPoints.objects.get_or_create(team=team)
        team_points.points = max(0, team_points.points - total_points)
        team_points.save()

        participation.rank = None
        participation.grade = None
        participation.marks = None
        participation.points_awarded = False
        participation.save()

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

    for program in Program.objects.all():
        calculate_and_award_points_for_program(program)

    messages.success(request, "✅ All rankings have been recalculated!")
    return redirect('enter_marks_summary')

@login_required
def get_programs_by_category(request):
    """AJAX view to get programs filtered by category"""
    category_id = request.GET.get('category_id')
    programs = []

    if category_id:
        try:
            programs_qs = Program.objects.filter(category_id=int(category_id)).order_by('name')
            programs = [{'id': p.id, 'name': p.name} for p in programs_qs]
        except (ValueError, TypeError):
            pass

    return JsonResponse({'programs': programs})

@login_required
def team_leaderboard(request):
    """Display team leaderboard with accurate points"""
    is_admin = request.user.role == 'admin'
    view_mode = request.GET.get('view', 'announced') if is_admin else 'announced'
    announced_only = (view_mode == 'announced')

    teams = Team.objects.all().order_by('name')

    team_stats = []
    for team in teams:
        total_points = recalculate_team_points(team, announced_only=announced_only)

        participations = Participation.objects.filter(contestant__team=team)
        if announced_only:
            participations = participations.filter(program__is_announced=True)
            
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

    team_stats.sort(key=lambda x: x['total_points'], reverse=True)

    current_rank = 1
    for i, stat in enumerate(team_stats):
        if i > 0 and stat['total_points'] < team_stats[i - 1]['total_points']:
            current_rank = i + 1
        stat['position'] = current_rank

    max_points = team_stats[0]['total_points'] if team_stats else 1

    return render(request, 'team_leaderboard.html', {
        'team_stats': team_stats,
        'top_teams': team_stats[:3],
        'total_teams': len(team_stats),
        'total_points_distributed': sum(s['total_points'] for s in team_stats),
        'is_admin': is_admin,
        'view_mode': view_mode,
        'announced_only': announced_only,
        'fest_name': SystemSetting.get_setting('fest_name', 'Madrasa Fest'),
        'max_points': max_points,
    })

@login_required
def team_detail(request, team_id):
    """Detailed view of a team's performance"""
    team = get_object_or_404(Team, id=team_id)

    is_admin = request.user.role == 'admin'
    view_mode = request.GET.get('view', 'announced') if is_admin else 'announced'
    announced_only = (view_mode == 'announced')

    total_points = recalculate_team_points(team, announced_only=announced_only)

    participations = Participation.objects.filter(
        contestant__team=team,
        marks__isnull=False
    )
    if announced_only:
        participations = participations.filter(program__is_announced=True)
        
    participations = participations.select_related('program', 'contestant').order_by('-marks')

    for p in participations:
        members_count = get_members_count_for_program(p.program) if p.program.is_group else 1
        rank_pts, grade_pts, total_pts = calculate_points(
            p.rank, p.grade, p.program.is_group, members_count
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
        'is_admin': is_admin,
        'view_mode': view_mode,
        'announced_only': announced_only,
    })

def view_results(request):
    """Public view of all program results"""
    is_admin = request.user.is_authenticated and request.user.role == 'admin'
    view_mode = request.GET.get('view', 'announced') if is_admin else 'announced'
    announced_only = (view_mode == 'announced')

    programs = Program.objects.filter(participation__marks__isnull=False).distinct()
    if announced_only:
        programs = programs.filter(is_announced=True)
    programs = programs.order_by('name')

    program_results = []
    for program in programs:
        results = (
            Participation.objects
            .filter(program=program, marks__isnull=False)
            .select_related('contestant', 'contestant__team')
            .order_by('rank')
        )

        members_count = get_members_count_for_program(program) if program.is_group else 1

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

    categories_query = Category.objects.filter(
        program__participation__marks__isnull=False
    ).distinct()
    if announced_only:
        categories_query = categories_query.filter(program__is_announced=True)
    categories = categories_query.order_by('name')

    suggested_announcements = get_top_5_balancing_announcement_suggestions() if is_admin else []

    return render(
        request,
        'view_results.html',
        {
            'program_results': program_results,
            'categories': categories,
            'is_admin': is_admin,
            'view_mode': view_mode,
            'announced_only': announced_only,
            'suggested_announcements': suggested_announcements,
        }
    )

def contestant_points_list(request):
    contestants = Contestant.objects.filter(
        category__name__in=["APEX", "CORTEX", "VERTEX"]
    ).distinct()

    contestant_results = []

    for contestant in contestants:
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
            rank_points = POINTS_FOR_RANK.get(p.rank, 0)
            grade_points = POINTS_FOR_GRADE.get(p.grade, 0) if p.grade else 0
            total = rank_points + grade_points if p.points_awarded else 0

            total_points += total

            program_details.append({
                "program_name": p.program.name,
                "program_category": p.program.category.name,
                "rank": p.rank,
                "grade": p.grade,
                "rank_points": rank_points,
                "grade_points": grade_points,
                "total_points": total
            })

        if program_details:
            contestant_results.append({
                "contestant": contestant,
                "programs": program_details,
                "total_points": total_points
            })

    contestant_results.sort(key=lambda x: x["total_points"], reverse=True)

    return render(request, "contestant_points.html", {
        "contestant_results": contestant_results
    })

@login_required
def update_settings(request):
    """Alias for system_config"""
    return system_config(request)

@login_required
def system_config(request):
    """Dedicated General System Configuration page (admin only)"""
    if request.user.role != 'admin':
        messages.error(request, 'Permission denied.')
        return redirect('dashboard_admin')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'reset_data':
            # Reset festival transactional data
            from ..models import ProgramSchedule
            Participation.objects.all().delete()
            GroupParticipation.objects.all().delete()
            Contestant.objects.all().delete()
            ProgramSchedule.objects.all().delete()
            TeamPoints.objects.all().delete()
            for team in Team.objects.all():
                team.total_points = 0
                team.save()
            Program.objects.update(is_announced=False, announced_at=None, result_number=None)
            messages.success(request, "All contestant, participation, score, and schedule data reset successfully.")
            return redirect('system_config')

        # Handle group point system
        group_point_system = request.POST.get('group_point_system')
        if group_point_system:
            if group_point_system in ['member_count', 'fixed']:
                setting, _ = SystemSetting.objects.get_or_create(key='group_point_system')
                setting.value = group_point_system
                setting.save()
                for team in Team.objects.all():
                    recalculate_team_points(team)
                messages.success(request, f"Group points system updated to: {'Fixed Rank Points (10, 6, 3)' if group_point_system == 'fixed' else 'Participant Count Multiplier'}")
            else:
                messages.error(request, "Invalid setting value.")

        # Handle fest name
        fest_name = request.POST.get('fest_name', '').strip()
        if fest_name:
            setting, _ = SystemSetting.objects.get_or_create(key='fest_name')
            setting.value = fest_name
            setting.save()
            messages.success(request, f"Fest name updated to: {fest_name}")
        elif 'fest_name' in request.POST:
            messages.error(request, "Fest name cannot be empty.")

        # Handle institution name
        institution_name = request.POST.get('institution_name', '').strip()
        if institution_name:
            setting, _ = SystemSetting.objects.get_or_create(key='institution_name')
            setting.value = institution_name
            setting.save()
            messages.success(request, f"Institution name updated to: {institution_name}")

        # Handle short name
        short_name = request.POST.get('short_name', '').strip()
        if short_name:
            setting, _ = SystemSetting.objects.get_or_create(key='short_name')
            setting.value = short_name
            setting.save()
            messages.success(request, f"Short name updated to: {short_name}")

        # Handle youtube embed url
        if 'youtube_embed_url' in request.POST:
            youtube_embed_url = request.POST.get('youtube_embed_url', '').strip()
            setting, _ = SystemSetting.objects.get_or_create(key='youtube_embed_url')
            setting.value = youtube_embed_url
            setting.save()
            messages.success(request, "YouTube Video Embed URL updated successfully.")

    # Build context
    group_point_system = SystemSetting.get_setting('group_point_system', 'member_count')
    fest_name = SystemSetting.get_setting('fest_name', 'Arts Fest')
    institution_name = SystemSetting.get_setting('institution_name', 'Campus / Institution')
    short_name = SystemSetting.get_setting('short_name', 'Fest Portal')
    youtube_embed_url = SystemSetting.get_setting('youtube_embed_url', '')
    total_programs = Program.objects.count()
    announced_programs = Program.objects.filter(is_announced=True).count()

    return render(request, 'system_config.html', {
        'group_point_system': group_point_system,
        'fest_name': fest_name,
        'institution_name': institution_name,
        'short_name': short_name,
        'youtube_embed_url': youtube_embed_url,
        'total_programs': total_programs,
        'announced_programs': announced_programs,
        'total_teams': Team.objects.count(),
        'total_contestants': Contestant.objects.count(),
    })



# =================== Group Marks & Scoring Views ===================

def create_group_participation(request):
    """Create a new group participation"""
    if request.method == 'POST':
        program_id = request.POST.get('program_id')
        contestant_ids = request.POST.getlist('contestants')
        group_name = request.POST.get('group_name', '')
        
        try:
            with transaction.atomic():
                program = get_object_or_404(Program, id=program_id, is_group=True)
                required_count = program.members_count or 1
                
                # Validate contestant count
                if len(contestant_ids) != required_count:
                    messages.error(request, f"Exact participant count required for {program.name} is {required_count}. You selected {len(contestant_ids)}.")
                    return redirect('group_participation_form')
                
                # Get contestants and validate they're from the same team
                contestants = Contestant.objects.filter(id__in=contestant_ids)
                teams = set(c.team for c in contestants if c.team)
                
                if not teams:
                    messages.error(request, "Selected contestants must belong to a team.")
                    return redirect('group_participation_form')

                if len(teams) > 1:
                    messages.error(request, "All contestants in a group must be from the same team.")
                    return redirect('group_participation_form')
                
                team = list(teams)[0]
                
                # Count existing groups for this team in this program
                existing_count = GroupParticipation.objects.filter(
                    program=program, team=team
                ).count()
                
                if not group_name:
                    group_name = f"{team.name} - Group {existing_count + 1}"
                
                # Create group participation
                group_participation = GroupParticipation.objects.create(
                    program=program,
                    team=team,
                    group_name=group_name
                )
                group_participation.contestants.set(contestants)
                
                messages.success(request, f"Group '{group_name}' created successfully for {program.name} ({len(contestants)} members)!")
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

def calculate_individual_grades_and_points():
    """Calculate grades, ranks, and points for individual participations"""
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
                
                # Award points to team
                # (delegates to the custom calculation / points system helper in scoring)
                # ...
                pass
                
    except Exception as e:
        print(f"Error in calculate_rankings_and_points: {e}")
        raise

def team_leaderboard2(request):
    """Display team leaderboard (alias for team_leaderboard)"""
    return team_leaderboard(request)

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

        # Pass category_id to get category-specific points
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

def recalculate_all_team_points():
    """Recalculate total points for all teams (both individual and group)"""
    # Reset all team points
    Team.objects.update(total_points=0)
    
    # Reset points awarded flags
    Participation.objects.update(points_awarded=False)
    GroupParticipation.objects.update(points_awarded=False)
    
    # Recalculate individual participations
    calculate_individual_grades_and_points()
    
    # Recalculate group participations
    calculate_group_grades_and_points()

def recalculate_points_view(request):
    """Manual recalculation of all points"""
    if request.method == 'POST':
        try:
            recalculate_all_team_points()
            messages.success(request, "All team points have been recalculated successfully!")
        except Exception as e:
            messages.error(request, f"Error recalculating points: {str(e)}")
    
    return redirect('team_leaderboard')

def results_page(request):
    return render(request, 'results_page.html')

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

    return render(request, 'enter_marks_summary_cat.html', {
        'participations': participations,
        'programs': programs,
        'categories': categories,
        'selected_program': selected_program,
        'selected_category': selected_category,
        'program_id': program_id,
        'category_id': category_id,
    })

# ================= Smart Announcement Assistant & Recommendation Engine =================

def get_top_5_balancing_announcement_suggestions():
    """
    Calculates top 5 unannounced completed programs that best balance 
    the current public team scores and create maximum suspense on the public leaderboard.
    """
    teams = list(Team.objects.all())
    if not teams:
        return []

    public_team_scores = {t.id: recalculate_team_points(t, announced_only=True) for t in teams}
    
    unannounced_programs = Program.objects.filter(
        is_announced=False
    ).filter(
        Q(participation__marks__isnull=False) | Q(groupparticipation__marks__isnull=False)
    ).distinct()

    suggestions = []
    for prog in unannounced_programs:
        simulated_gains = {t.id: 0 for t in teams}
        
        if prog.is_group:
            gps = GroupParticipation.objects.filter(program=prog, marks__isnull=False)
            for gp in gps:
                if gp.team_id and gp.rank:
                    pts = calculate_points(gp.rank, gp.grade, is_group=True, members_count=prog.members_count or 1)[2]
                    simulated_gains[gp.team_id] = simulated_gains.get(gp.team_id, 0) + pts
        else:
            ps = Participation.objects.filter(program=prog, marks__isnull=False).select_related('contestant')
            for p in ps:
                if p.contestant and p.contestant.team_id and p.rank:
                    pts = calculate_points(p.rank, p.grade, is_group=False, members_count=1)[2]
                    simulated_gains[p.contestant.team_id] = simulated_gains.get(p.contestant.team_id, 0) + pts

        simulated_scores = {t.id: public_team_scores[t.id] + simulated_gains[t.id] for t in teams}
        sorted_scores = sorted(simulated_scores.values(), reverse=True)
        
        if len(sorted_scores) >= 2:
            gap_1st_2nd = sorted_scores[0] - sorted_scores[1]
            gap_1st_3rd = sorted_scores[0] - sorted_scores[2] if len(sorted_scores) >= 3 else gap_1st_2nd
            balance_score = -(gap_1st_2nd * 1.5 + gap_1st_3rd * 0.5)
        else:
            balance_score = 0

        total_prog_pts = sum(simulated_gains.values())
        final_priority = balance_score + (total_prog_pts * 0.1)

        impact_items = []
        for t in teams:
            gain = simulated_gains.get(t.id, 0)
            if gain > 0:
                impact_items.append(f"{t.name}: +{gain} pts")

        suggestions.append({
            'program': prog,
            'total_pts': total_prog_pts,
            'priority': round(final_priority, 2),
            'impact_summary': ", ".join(impact_items) if impact_items else "No team points awarded",
            'top_gap_after': sorted_scores[0] - sorted_scores[1] if len(sorted_scores) >= 2 else 0
        })

    suggestions.sort(key=lambda x: x['priority'], reverse=True)
    return suggestions[:5]

@login_required
def toggle_program_announcement(request, program_id):
    """Toggle announcement status for a program and update timestamp"""
    if request.user.role != 'admin':
        messages.error(request, 'Permission denied.')
        return redirect('dashboard_admin')

    program = get_object_or_404(Program, id=program_id)
    program.is_announced = not program.is_announced
    if program.is_announced:
        program.announced_at = timezone.now()
        messages.success(request, f"📢 Results for '{program.name}' are now PUBLICLY ANNOUNCED!")
    else:
        messages.info(request, f"🔒 Results for '{program.name}' are now hidden from public views.")
    program.save()

    for team in Team.objects.all():
        recalculate_team_points(team)

    next_url = request.META.get('HTTP_REFERER') or redirect('dashboard_admin')
    return redirect(next_url)

@login_required
def manage_announcements(request):
    """Admin page for managing result announcements with smart balancing suggestions"""
    if request.user.role != 'admin':
        messages.error(request, 'Permission denied.')
        return redirect('dashboard_admin')

    programs = Program.objects.select_related('category').order_by('category__name', 'name')
    
    for p in programs:
        if p.is_group:
            p.has_marks = GroupParticipation.objects.filter(program=p, marks__isnull=False).exists()
            p.marked_count = GroupParticipation.objects.filter(program=p, marks__isnull=False).count()
        else:
            p.has_marks = Participation.objects.filter(program=p, marks__isnull=False).exists()
            p.marked_count = Participation.objects.filter(program=p, marks__isnull=False).count()

    announced_count = programs.filter(is_announced=True).count()
    total_programs = programs.count()
    suggested_announcements = get_top_5_balancing_announcement_suggestions()

    return render(request, 'manage_announcements.html', {
        'programs': programs,
        'announced_count': announced_count,
        'total_programs': total_programs,
        'suggested_announcements': suggested_announcements,
    })

@login_required
def bulk_announce_programs(request):
    """Bulk announce or hide selected programs"""
    if request.user.role != 'admin':
        messages.error(request, 'Permission denied.')
        return redirect('dashboard_admin')

    if request.method == 'POST':
        action = request.POST.get('action')
        program_ids = request.POST.getlist('program_ids')
        
        if not program_ids:
            messages.warning(request, 'No programs selected.')
            return redirect('manage_announcements')

        if action == 'announce':
            Program.objects.filter(id__in=program_ids).update(
                is_announced=True,
                announced_at=timezone.now()
            )
            messages.success(request, f"📢 Announced {len(program_ids)} programs successfully!")
        elif action == 'unannounce':
            Program.objects.filter(id__in=program_ids).update(
                is_announced=False
            )
            messages.info(request, f"🔒 Hidden {len(program_ids)} programs from public view.")

        for team in Team.objects.all():
            recalculate_team_points(team)

    return redirect('manage_announcements')

@login_required
def announcement_balancer(request):
    """Dedicated Admin Assistant page for recommending Top 5 team-balancing announcements"""
    if request.user.role != 'admin':
        messages.error(request, 'Permission denied.')
        return redirect('dashboard_admin')

    teams = list(Team.objects.all())
    public_team_scores = {t.name: recalculate_team_points(t, announced_only=True) for t in teams}
    suggested_announcements = get_top_5_balancing_announcement_suggestions()

    return render(request, 'announcement_balancer.html', {
        'suggested_announcements': suggested_announcements,
        'public_team_scores': public_team_scores,
    })

def shareable_results_view(request):
    """Public page with shareable winner cards (1st, 2nd, 3rd rank) downloadable as JPEG"""
    programs = Program.objects.filter(is_announced=True).distinct()
    
    cards_data = []
    for prog in programs:
        if prog.is_group:
            winners = GroupParticipation.objects.filter(
                program=prog,
                rank__in=[1, 2, 3]
            ).select_related('team').prefetch_related('contestants').order_by('rank')
            
            winners_list = []
            for gp in winners:
                members = ", ".join([c.name for c in gp.contestants.all()])
                winners_list.append({
                    'rank': gp.rank,
                    'name': gp.group_name or f"Group {gp.code_letter or ''}",
                    'team': gp.team.name if gp.team else '',
                    'members': members,
                    'marks': gp.marks,
                    'grade': gp.grade
                })
        else:
            winners = Participation.objects.filter(
                program=prog,
                rank__in=[1, 2, 3]
            ).select_related('contestant', 'contestant__team').order_by('rank')
            
            winners_list = []
            for p in winners:
                winners_list.append({
                    'rank': p.rank,
                    'name': p.contestant.name if p.contestant else '',
                    'team': p.contestant.team.name if p.contestant and p.contestant.team else '',
                    'members': '',
                    'marks': p.marks,
                    'grade': p.grade
                })

        if winners_list:
            cards_data.append({
                'program': prog,
                'winners': winners_list
            })

    fest_name = SystemSetting.get_setting('fest_name', 'Madrasa Fest')
    institution_name = SystemSetting.get_setting('institution_name', 'Campus / Institution')
    return render(request, 'shareable_results.html', {
        'cards_data': cards_data,
        'fest_name': fest_name,
        'institution_name': institution_name,
    })



