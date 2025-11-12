from datetime import timezone
from django.utils import timezone
from django.shortcuts import get_object_or_404, render, redirect
from core.models import Participation, Program, Team
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Count, Sum, Q
from core.views import get_members_count_for_program, calculate_points

# Create your views here.
# ==================== VIEWS ====================

# 1. Admin: Toggle Announcement
@login_required
def toggle_program_announcement(request, program_id):
    """Toggle program result announcement status"""
    if request.user.role != 'admin':
        messages.error(request, 'Permission denied.')
        return redirect('dashboard_team')
    
    program = get_object_or_404(Program, id=program_id)
    
    if program.is_announced:
        # Unannounce
        program.is_announced = False
        program.announced_at = None
        messages.success(request, f"Results for '{program.name}' are now hidden from public.")
    else:
        # Announce
        program.is_announced = True
        program.announced_at = timezone.now()
        messages.success(request, f"Results for '{program.name}' are now public!")
    
    program.save()
    return redirect(request.META.get('HTTP_REFERER', 'enter_marks_summary'))


# 2. Admin: Bulk Announce/Unannounce
@login_required
def bulk_announce_programs(request):
    """Announce or unannounce multiple programs at once"""
    if request.user.role != 'admin':
        messages.error(request, 'Permission denied.')
        return redirect('dashboard_team')
    
    if request.method == 'POST':
        program_ids = request.POST.getlist('program_ids')
        action = request.POST.get('action')  # 'announce' or 'unannounce'
        
        if program_ids:
            programs = Program.objects.filter(id__in=program_ids)
            
            if action == 'announce':
                programs.update(is_announced=True, announced_at=timezone.now())
                messages.success(request, f"{programs.count()} programs announced!")
            elif action == 'unannounce':
                programs.update(is_announced=False, announced_at=None)
                messages.success(request, f"{programs.count()} programs hidden from public!")
    
    return redirect('manage_announcements')


# 3. Admin: Manage Announcements Page
@login_required
def manage_announcements(request):
    """Admin page to manage which results are public"""
    if request.user.role != 'admin':
        return redirect('dashboard_team')
    
# Get all programs with participation stats
    programs = Program.objects.annotate(
        total_participants=Count('participation'),
        marked_participants=Count('participation', filter=Q(participation__marks__isnull=False))
    ).order_by('category__name', 'name')
    
    context = {
        'programs': programs,
        'announced_count': programs.filter(is_announced=True).count(),
        'total_programs': programs.count(),
    }
    
    return render(request, 'announcements/manage_announcements.html', context)


# 4. Public: Program Tiles (Home Page)
def public_results_home(request):
    """Public page showing announced program tiles"""
    # Only show announced programs with results
    announced_programs = Program.objects.filter(
        is_announced=True,
        participation__marks__isnull=False
    ).distinct().annotate(
        participants_count=Count('participation', filter=Q(participation__marks__isnull=False))
    ).order_by('category__name', 'name')
    
    # Group by category
    categories = {}
    for program in announced_programs:
        category_name = program.category.name if program.category else "Other"
        if category_name not in categories:
            categories[category_name] = []
        categories[category_name].append(program)
    
    return render(request, 'announcements/public_results_home.html', {
        'categories': categories,
        'total_programs': announced_programs.count(),
    })


# 5. Public: Single Program Result
def public_program_result(request, program_id):
    """Public view of a single program's results"""
    program = get_object_or_404(Program, id=program_id)
    
    # Check if announced
    if not program.is_announced:
        messages.warning(request, "Results for this program are not yet announced.")
        return redirect('public_results_home')
    
    # Get results
    results = Participation.objects.filter(
        program=program,
        marks__isnull=False
    ).exclude(marks=0).select_related(
        'contestant', 'contestant__team'
    ).order_by('rank')
    
    # Calculate display points
    members_count = get_members_count_for_program(program) if program.is_group else 1
    
    for p in results:
        if p.marks and p.marks > 0:
            rank_pts, grade_pts, total_pts = calculate_points(
                p.rank, p.grade, program.is_group, members_count
            )
            p.rank_points = rank_pts
            p.grade_points = grade_pts
            p.total_points = total_pts
        else:
            p.rank_points = 0
            p.grade_points = 0
            p.total_points = 0
    
    # Separate winners and others
    winners = results.filter(rank__in=[1, 2, 3])
    others = results.exclude(rank__in=[1, 2, 3])
    
    return render(request, 'announcements/public_program_result.html', {
        'program': program,
        'results': results,
        'winners': winners,
        'others': others,
        'is_group': program.is_group,
        'members_count': members_count,
    })


# 6. Public: Leaderboard (Only Announced Programs)
def public_leaderboard(request):
    """Public leaderboard showing only announced program points"""
    teams = Team.objects.all().order_by('name')
    
    team_data = []
    for team in teams:
        # Calculate points ONLY from announced programs
        participations = Participation.objects.filter(
            contestant__team=team,
            points_awarded=True,
            marks__isnull=False,
            program__is_announced=True  # Only announced programs
        ).select_related('program', 'contestant__category')
        
        total_points = 0
        for p in participations:
            if p.marks and p.marks > 0:
                is_group = p.program.is_group
                contestant_count = get_members_count_for_program(p.program) if is_group else 1
                _, _, points = calculate_points(p.rank, p.grade, is_group, contestant_count)
                total_points += points
        
        # Get stats
        winners_count = participations.filter(rank__in=[1, 2, 3]).count()
        
        team_data.append({
            'team': team,
            'points': total_points,
            'total_participations': participations.count(),
            'winners_count': winners_count,
            'first_place': participations.filter(rank=1).count(),
            'second_place': participations.filter(rank=2).count(),
            'third_place': participations.filter(rank=3).count(),
        })
    
    # Sort by points
    team_data.sort(key=lambda x: x['points'], reverse=True)
    
    # Add positions
    for i, data in enumerate(team_data, 1):
        data['position'] = i
    
    # Get announced programs count
    announced_count = Program.objects.filter(is_announced=True).count()
    
    return render(request, 'announcements/public_leaderboard.html', {
        'teams': team_data,
        'top_three': team_data[:3] if len(team_data) >= 3 else team_data,
        'announced_programs_count': announced_count,
    })
