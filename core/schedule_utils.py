from datetime import datetime, timedelta, time
from django.db.models import Q
from core.models import Program, FestDay, Stage, ProgramSchedule, Participation, GroupParticipation, Contestant

def get_program_assigned_count(program):
    """Return total assigned contestants or group entries for a program."""
    if program.is_group:
        return GroupParticipation.objects.filter(program=program).count()
    return Participation.objects.filter(program=program).count()

def calculate_program_duration(program):
    """
    Calculates total program duration in minutes based on participant count.
    Total = (assigned_count * duration_per_participant) + buffer_margin_minutes
    """
    count = get_program_assigned_count(program)
    if count == 0:
        count = 1  # Default fallback calculation if no participants yet
    duration = (count * program.duration_per_participant) + (program.buffer_margin_minutes or 0)
    return max(duration, 5)  # Minimum 5 minutes

def get_program_contestants(program):
    """Return a QuerySet or list of Contestant objects for a given program."""
    if program.is_group:
        gps = GroupParticipation.objects.filter(program=program).prefetch_related('contestants')
        contestant_ids = set()
        for gp in gps:
            for c in gp.contestants.all():
                contestant_ids.add(c.id)
        return Contestant.objects.filter(id__in=contestant_ids)
    else:
        ps = Participation.objects.filter(program=program).select_related('contestant')
        return Contestant.objects.filter(id__in=[p.contestant_id for p in ps if p.contestant_id])

def times_overlap(start1, end1, start2, end2):
    """Return True if time range [start1, end1] overlaps with [start2, end2]."""
    return max(start1, start2) < min(end1, end2)

def detect_all_clashes():
    """
    Analyzes all ProgramSchedules and returns a breakdown of:
    - stage_clashes: Same day & stage overlapping programs
    - participant_clashes: Same contestant in overlapping programs on the same day
    - venue_mismatches: STAGE program on OFF_STAGE venue or vice versa
    """
    schedules = list(ProgramSchedule.objects.select_related('program', 'fest_day', 'stage', 'program__category').all())
    
    stage_clashes = []
    participant_clashes = []
    venue_mismatches = []

    # 1. Check Venue Mismatches
    for sched in schedules:
        if sched.program.program_type != sched.stage.stage_type:
            venue_mismatches.append({
                'schedule': sched,
                'program': sched.program,
                'stage': sched.stage,
                'program_type': sched.program.get_program_type_display(),
                'stage_type': sched.stage.get_stage_type_display(),
            })

    # Pre-cache contestants per program
    program_contestant_map = {}
    for sched in schedules:
        program_contestant_map[sched.program_id] = set(get_program_contestants(sched.program).values_list('id', flat=True))

    # 2. Check Stage & Participant Overlaps
    n = len(schedules)
    for i in range(n):
        s1 = schedules[i]
        for j in range(i + 1, n):
            s2 = schedules[j]

            # Clashes only possible on the same Fest Day
            if s1.fest_day_id != s2.fest_day_id:
                continue

            # Check time overlap
            if times_overlap(s1.start_time, s1.end_time, s2.start_time, s2.end_time):
                start_str = max(s1.start_time, s2.start_time).strftime("%I:%M %p")
                end_str = min(s1.end_time, s2.end_time).strftime("%I:%M %p")
                overlap_time_range = f"{start_str} - {end_str}"

                # 2a. Stage Overlap (Same day & Same Stage)
                if s1.stage_id == s2.stage_id:
                    stage_clashes.append({
                        'schedule1': s1,
                        'schedule2': s2,
                        'fest_day': s1.fest_day,
                        'stage': s1.stage,
                        'overlap_range': overlap_time_range
                    })

                # 2b. Participant Overlap (Common contestants)
                common_c_ids = program_contestant_map.get(s1.program_id, set()) & program_contestant_map.get(s2.program_id, set())
                if common_c_ids:
                    common_contestants = Contestant.objects.filter(id__in=common_c_ids).select_related('team')
                    for contestant in common_contestants:
                        participant_clashes.append({
                            'contestant': contestant,
                            'schedule1': s1,
                            'schedule2': s2,
                            'fest_day': s1.fest_day,
                            'overlap_range': overlap_time_range
                        })

    total_clash_count = len(stage_clashes) + len(participant_clashes) + len(venue_mismatches)
    
    return {
        'stage_clashes': stage_clashes,
        'participant_clashes': participant_clashes,
        'venue_mismatches': venue_mismatches,
        'total_clash_count': total_clash_count
    }

def generate_smart_auto_schedule(daily_start=time(9, 0), daily_end=time(17, 0), buffer_between_programs_mins=5):
    """
    Auto-schedules all unscheduled programs across available FestDays and Stages.
    Respects:
    1. STAGE programs -> STAGE venues, OFF_STAGE programs -> OFF_STAGE venues
    2. Program total duration (participants * mins_per_part + buffer)
    3. Stage time availability (no stage overlaps)
    4. Participant time availability (no participant clashes)
    """
    fest_days = list(FestDay.objects.all().order_by('day_number'))
    stages = list(Stage.objects.all().order_by('stage_type', 'name'))

    if not fest_days or not stages:
        return {'error': 'Please add at least one Fest Day and one Stage before running Auto-Scheduler.'}

    # Fetch unscheduled programs
    scheduled_prog_ids = ProgramSchedule.objects.values_list('program_id', flat=True)
    unscheduled_programs = list(Program.objects.exclude(id__in=scheduled_prog_ids).select_related('category'))

    if not unscheduled_programs:
        return {'message': 'All programs are already scheduled!'}

    # Bookings tracker: (fest_day_id, stage_id) -> list of (start_dt, end_dt)
    stage_bookings = {}
    for day in fest_days:
        for st in stages:
            stage_bookings[(day.id, st.id)] = []

    # Participant bookings tracker: (fest_day_id, contestant_id) -> list of (start_dt, end_dt)
    contestant_bookings = {}

    # Pre-fill existing bookings from database
    for existing_sched in ProgramSchedule.objects.all():
        d_id = existing_sched.fest_day_id
        st_id = existing_sched.stage_id
        s_dt = datetime.combine(datetime.today(), existing_sched.start_time)
        e_dt = datetime.combine(datetime.today(), existing_sched.end_time)
        
        stage_bookings.setdefault((d_id, st_id), []).append((s_dt, e_dt))

        # Record contestant bookings
        c_ids = set(get_program_contestants(existing_sched.program).values_list('id', flat=True))
        for c_id in c_ids:
            contestant_bookings.setdefault((d_id, c_id), []).append((s_dt, e_dt))

    scheduled_count = 0
    skipped_programs = []

    base_date = datetime.today().date()
    day_start_dt = datetime.combine(base_date, daily_start)
    day_end_dt = datetime.combine(base_date, daily_end)

    for program in unscheduled_programs:
        dur_mins = calculate_program_duration(program)
        dur_td = timedelta(minutes=dur_mins)
        buf_td = timedelta(minutes=buffer_between_programs_mins)

        c_ids = set(get_program_contestants(program).values_list('id', flat=True))
        target_stage_type = program.program_type
        valid_stages = [st for st in stages if st.stage_type == target_stage_type]

        if not valid_stages:
            # Fallback to any stage if no matching venue type exists
            valid_stages = stages

        is_placed = False

        for day in fest_days:
            if is_placed:
                break

            for stage in valid_stages:
                if is_placed:
                    break

                # Try finding a slot starting from day_start_dt up to day_end_dt
                curr_start = day_start_dt
                
                while curr_start + dur_td <= day_end_dt:
                    curr_end = curr_start + dur_td

                    # Check stage conflict
                    stage_conflict = False
                    for b_start, b_end in stage_bookings.get((day.id, stage.id), []):
                        if times_overlap(curr_start, curr_end, b_start, b_end):
                            stage_conflict = True
                            # Jump to end of conflicting booking + buffer
                            curr_start = b_end + buf_td
                            break

                    if stage_conflict:
                        continue

                    # Check contestant conflict
                    contestant_conflict = False
                    if c_ids:
                        for c_id in c_ids:
                            for c_start, c_end in contestant_bookings.get((day.id, c_id), []):
                                if times_overlap(curr_start, curr_end, c_start, c_end):
                                    contestant_conflict = True
                                    break
                            if contestant_conflict:
                                break

                    if contestant_conflict:
                        # Increment by 5 mins to search next slot
                        curr_start += timedelta(minutes=5)
                        continue

                    # Found a valid conflict-free slot!
                    ProgramSchedule.objects.create(
                        program=program,
                        fest_day=day,
                        stage=stage,
                        start_time=curr_start.time(),
                        end_time=curr_end.time(),
                        total_duration_minutes=dur_mins
                    )

                    # Update trackers
                    stage_bookings[(day.id, stage.id)].append((curr_start, curr_end))
                    for c_id in c_ids:
                        contestant_bookings.setdefault((day.id, c_id), []).append((curr_start, curr_end))

                    scheduled_count += 1
                    is_placed = True
                    break

        if not is_placed:
            skipped_programs.append(program.name)

    return {
        'scheduled_count': scheduled_count,
        'skipped_count': len(skipped_programs),
        'skipped_programs': skipped_programs
    }
