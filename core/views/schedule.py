from datetime import datetime, time, timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from core.models import Program, FestDay, Stage, ProgramSchedule
from core.schedule_utils import (
    get_program_assigned_count,
    calculate_program_duration,
    detect_all_clashes,
    generate_smart_auto_schedule
)

@login_required
def manage_schedule(request):
    if not (request.user.is_superuser or request.user.is_staff or request.user.role == 'admin'):
        messages.error(request, "Access denied. Admin privileges required.")
        return redirect('face_page')

    fest_days = FestDay.objects.all().order_by('day_number')
    stages = Stage.objects.all().order_by('stage_type', 'name')
    programs = Program.objects.select_related('category', 'schedule', 'schedule__fest_day', 'schedule__stage').all()

    # Pre-calculate assigned counts & duration for each program
    program_list = []
    scheduled_count = 0
    for p in programs:
        assigned_count = get_program_assigned_count(p)
        calc_dur = calculate_program_duration(p)
        has_sched = hasattr(p, 'schedule') and p.schedule is not None
        if has_sched:
            scheduled_count += 1

        program_list.append({
            'program': p,
            'assigned_count': assigned_count,
            'calculated_duration': calc_dur,
            'has_schedule': has_sched,
            'schedule': p.schedule if has_sched else None
        })

    clash_data = detect_all_clashes()

    # Master timetable matrix grouped by FestDay and Stage
    timetable_by_day = []
    for day in fest_days:
        day_stages = []
        for stage in stages:
            schedules = ProgramSchedule.objects.filter(fest_day=day, stage=stage).select_related('program', 'program__category').order_by('start_time')
            day_stages.append({
                'stage': stage,
                'schedules': schedules
            })
        timetable_by_day.append({
            'day': day,
            'stages': day_stages
        })

    context = {
        'fest_days': fest_days,
        'stages': stages,
        'program_list': program_list,
        'total_programs': len(programs),
        'scheduled_count': scheduled_count,
        'clash_data': clash_data,
        'timetable_by_day': timetable_by_day
    }
    return render(request, 'manage_schedule.html', context)

@login_required
def add_fest_day(request):
    if not (request.user.is_superuser or request.user.is_staff or request.user.role == 'admin') or request.method != 'POST':
        return redirect('manage_schedule')

    day_number = request.POST.get('day_number')
    date_str = request.POST.get('date')
    name = request.POST.get('name', '').strip()
    start_time_str = request.POST.get('start_time', '09:00')
    end_time_str = request.POST.get('end_time', '21:00')

    if day_number:
        parsed_date = None
        if date_str:
            try:
                parsed_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                pass

        try:
            st_time = datetime.strptime(start_time_str, '%H:%M').time()
        except ValueError:
            st_time = time(9, 0)

        try:
            en_time = datetime.strptime(end_time_str, '%H:%M').time()
        except ValueError:
            en_time = time(21, 0)
        
        FestDay.objects.get_or_create(
            day_number=int(day_number),
            defaults={'date': parsed_date, 'name': name, 'start_time': st_time, 'end_time': en_time}
        )
        messages.success(request, f"Fest Day {day_number} added successfully!")

    return redirect('manage_schedule')

@login_required
def delete_fest_day(request, day_id):
    if not (request.user.is_superuser or request.user.is_staff or request.user.role == 'admin') or request.method != 'POST':
        return redirect('manage_schedule')

    day = get_object_or_404(FestDay, id=day_id)
    day_num = day.day_number
    day.delete()
    messages.success(request, f"Fest Day {day_num} deleted.")
    return redirect('manage_schedule')

@login_required
def add_stage(request):
    if not (request.user.is_superuser or request.user.is_staff or request.user.role == 'admin') or request.method != 'POST':
        return redirect('manage_schedule')

    name = request.POST.get('name', '').strip()
    stage_type = request.POST.get('stage_type', 'STAGE')
    location_details = request.POST.get('location_details', '').strip()

    if name:
        Stage.objects.create(
            name=name,
            stage_type=stage_type,
            location_details=location_details
        )
        messages.success(request, f"Venue '{name}' ({stage_type}) added successfully!")

    return redirect('manage_schedule')

@login_required
def delete_stage(request, stage_id):
    if not (request.user.is_superuser or request.user.is_staff or request.user.role == 'admin') or request.method != 'POST':
        return redirect('manage_schedule')

    stage = get_object_or_404(Stage, id=stage_id)
    st_name = stage.name
    stage.delete()
    messages.success(request, f"Venue '{st_name}' deleted.")
    return redirect('manage_schedule')

@login_required
def update_program_duration(request, program_id):
    if not (request.user.is_superuser or request.user.is_staff or request.user.role == 'admin') or request.method != 'POST':
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('is_ajax') == '1':
            return JsonResponse({'status': 'error', 'message': 'Access denied'}, status=403)
        return redirect('manage_schedule')

    program = get_object_or_404(Program, id=program_id)
    program_type = request.POST.get('program_type', 'STAGE')
    presentation_mode = request.POST.get('presentation_mode', 'SEQUENTIAL')
    dur_per_part = request.POST.get('duration_per_participant', '5')
    buffer_mins = request.POST.get('buffer_margin_minutes', '0')
    preferred_stage_id = request.POST.get('preferred_stage_id', '')

    program.program_type = program_type
    program.presentation_mode = presentation_mode
    program.duration_per_participant = max(int(dur_per_part), 1)
    program.buffer_margin_minutes = max(int(buffer_mins), 0)

    if preferred_stage_id:
        program.preferred_stage_id = int(preferred_stage_id)
    else:
        program.preferred_stage = None

    program.save()

    calc_dur = calculate_program_duration(program)
    
    # Update active schedule end_time & total_duration_minutes if schedule exists
    if hasattr(program, 'schedule') and program.schedule is not None:
        sched = program.schedule
        sched.total_duration_minutes = calc_dur
        s_dt = datetime.combine(datetime.today(), sched.start_time)
        sched.end_time = (s_dt + timedelta(minutes=calc_dur)).time()
        sched.save()

    clash_data = detect_all_clashes()

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('is_ajax') == '1':
        return JsonResponse({
            'status': 'success',
            'program_id': program.id,
            'program_name': program.name,
            'calculated_duration': calc_dur,
            'total_clashes': clash_data['total_clash_count']
        })

    messages.success(request, f"Schedule settings for '{program.name}' updated.")
    return redirect('manage_schedule')

@login_required
def save_program_schedule(request):
    if not (request.user.is_superuser or request.user.is_staff or request.user.role == 'admin') or request.method != 'POST':
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('is_ajax') == '1':
            return JsonResponse({'status': 'error', 'message': 'Access denied'}, status=403)
        return redirect('manage_schedule')

    program_id = request.POST.get('program_id')
    fest_day_id = request.POST.get('fest_day_id')
    stage_id = request.POST.get('stage_id')
    start_time_str = request.POST.get('start_time')
    end_time_str = request.POST.get('end_time')

    if program_id and fest_day_id and stage_id and start_time_str:
        program = get_object_or_404(Program, id=program_id)
        fest_day = get_object_or_404(FestDay, id=fest_day_id)
        stage = get_object_or_404(Stage, id=stage_id)

        try:
            start_t = datetime.strptime(start_time_str, '%H:%M').time()
        except ValueError:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('is_ajax') == '1':
                return JsonResponse({'status': 'error', 'message': 'Invalid start time format.'}, status=400)
            messages.error(request, "Invalid start time format.")
            return redirect('manage_schedule')

        calc_mins = calculate_program_duration(program)

        if end_time_str:
            try:
                end_t = datetime.strptime(end_time_str, '%H:%M').time()
            except ValueError:
                end_t = (datetime.combine(datetime.today(), start_t) + timedelta(minutes=calc_mins)).time()
        else:
            end_t = (datetime.combine(datetime.today(), start_t) + timedelta(minutes=calc_mins)).time()

        sched, created = ProgramSchedule.objects.update_or_create(
            program=program,
            defaults={
                'fest_day': fest_day,
                'stage': stage,
                'start_time': start_t,
                'end_time': end_t,
                'total_duration_minutes': calc_mins
            }
        )

        clash_data = detect_all_clashes()

        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('is_ajax') == '1':
            slot_text = f"Day {fest_day.day_number} @ {stage.name} ({start_t.strftime('%I:%M %p')} - {end_t.strftime('%I:%M %p')})"
            return JsonResponse({
                'status': 'success',
                'program_id': program.id,
                'schedule_id': sched.id,
                'slot_text': slot_text,
                'total_clashes': clash_data['total_clash_count']
            })

        messages.success(request, f"Schedule saved for '{program.name}'.")

    return redirect('manage_schedule')

@login_required
def delete_program_schedule(request, schedule_id):
    if not (request.user.is_superuser or request.user.is_staff or request.user.role == 'admin') or request.method != 'POST':
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('is_ajax') == '1':
            return JsonResponse({'status': 'error', 'message': 'Access denied'}, status=403)
        return redirect('manage_schedule')

    sched = get_object_or_404(ProgramSchedule, id=schedule_id)
    prog_id = sched.program_id
    prog_name = sched.program.name
    sched.delete()

    clash_data = detect_all_clashes()

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('is_ajax') == '1':
        return JsonResponse({
            'status': 'success',
            'program_id': prog_id,
            'total_clashes': clash_data['total_clash_count']
        })

    messages.success(request, f"Schedule for '{prog_name}' removed.")
    return redirect('manage_schedule')

@login_required
def run_auto_scheduler(request):
    if not (request.user.is_superuser or request.user.is_staff or request.user.role == 'admin') or request.method != 'POST':
        return redirect('manage_schedule')

    res = generate_smart_auto_schedule()

    if 'error' in res:
        messages.error(request, res['error'])
    else:
        sched_count = res.get('scheduled_count', 0)
        skip_count = res.get('skipped_count', 0)
        messages.success(request, f"Smart Auto-Scheduler completed! Successfully scheduled {sched_count} programs.")
        if skip_count > 0:
            messages.warning(request, f"Could not fit {skip_count} programs into available time slots. Consider adding another fest day/stage or extending operating hours.")

    return redirect('manage_schedule')

    if 'error' in res:
        messages.error(request, res['error'])
    else:
        sched_count = res.get('scheduled_count', 0)
        skip_count = res.get('skipped_count', 0)
        messages.success(request, f"Auto-Scheduler completed! Successfully scheduled {sched_count} programs.")
        if skip_count > 0:
            messages.warning(request, f"Could not fit {skip_count} programs into available time slots. Consider adding another fest day/stage or extending hours.")

    return redirect('manage_schedule')

@login_required
def clear_all_schedules(request):
    if not (request.user.is_superuser or request.user.is_staff or request.user.role == 'admin') or request.method != 'POST':
        return redirect('manage_schedule')

    count = ProgramSchedule.objects.count()
    ProgramSchedule.objects.all().delete()
    messages.success(request, f"Cleared all {count} program schedules.")
    return redirect('manage_schedule')

@login_required
def view_clashes(request):
    if not (request.user.is_superuser or request.user.is_staff or request.user.role == 'admin'):
        messages.error(request, "Access denied. Admin privileges required.")
        return redirect('face_page')

    clash_data = detect_all_clashes()
    return render(request, 'view_clashes.html', {'clash_data': clash_data})
