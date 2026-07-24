from datetime import timezone
from django.utils import timezone
from django.db import models
from django.utils import timezone
from django.contrib.auth.models import AbstractUser

# ----------------- Custom User -----------------
class User(AbstractUser):
    ROLE_CHOICES = (
        ('admin', 'Admin'),
        ('team', 'Team'),
        ('off_campus', 'Off_campus')
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    is_approved = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if self.is_superuser or self.is_staff or self.role == 'admin':
            self.is_approved = True
            if (self.is_superuser or self.is_staff) and self.role != 'admin':
                self.role = 'admin'
        super().save(*args, **kwargs)

# ----------------- Admin Profile -----------------
class AdminProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    designation = models.CharField(max_length=100, default='Coordinator')


# -------------------campus - offcampus separation ----------------
class Competition(models.Model):
    COMPETITION_TYPES = [
        ("ON", "On-Campus"),
        ("OFF", "Off-Campus"),
    ]
    name = models.CharField(max_length=100)
    type = models.CharField(max_length=3, choices=COMPETITION_TYPES)
    year = models.PositiveIntegerField(default=2025)  # optional, if yearly fest
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"{self.name} ({self.get_type_display()})"


# ----------------- Team -----------------
class Team(models.Model):
    competition = models.ForeignKey(Competition, on_delete=models.CASCADE, null=True, blank=True)
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    total_points = models.IntegerField(default=0)
    # Add fields: college, district etc.
    def __str__(self): return self.name

# ----------------- Category -----------------
class Category(models.Model):
    COMPETITION_TYPES = [
        ('MAIN', 'Main Campus'),
        ('OFF', 'Off Campus'),
    ]
    name = models.CharField(max_length=100)
    competition_type = models.CharField(max_length=10, choices=COMPETITION_TYPES, default='MAIN')

    def __str__(self):
        return f"{self.name} ({self.get_competition_type_display()})"


# ----------------- Program -----------------
class Program(models.Model):
    PROGRAM_TYPES = (
        ('STAGE', 'Stage Program'),
        ('OFF_STAGE', 'Off-Stage Program'),
    )
    PRESENTATION_MODES = (
        ('SEQUENTIAL', 'Per Participant (Sequential)'),
        ('SIMULTANEOUS', 'All-at-Once (Simultaneous/Written)'),
    )
    competition = models.ForeignKey(Competition, on_delete=models.CASCADE, null=True, blank=True)
    name = models.CharField(max_length=100)
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    is_group = models.BooleanField(default=False, null=True)
    members_count = models.PositiveIntegerField(null=True, blank=True, default=1)
    program_type = models.CharField(max_length=15, choices=PROGRAM_TYPES, default='STAGE')
    presentation_mode = models.CharField(max_length=15, choices=PRESENTATION_MODES, default='SEQUENTIAL', help_text="Sequential (Speech/Song) vs Simultaneous (Essay/Drawing)")
    duration_per_participant = models.PositiveIntegerField(default=5, help_text="Duration in minutes per participant (or total fixed mins if simultaneous)")
    buffer_margin_minutes = models.PositiveIntegerField(default=0, help_text="Extra buffer time in minutes")
    preferred_stage = models.ForeignKey('Stage', on_delete=models.SET_NULL, null=True, blank=True, related_name='preferred_programs', help_text="Priority stage venue for popular events")
    is_announced = models.BooleanField(default=False, help_text="Make results public")
    announced_at = models.DateTimeField(null=True, blank=True)
    result_number = models.PositiveIntegerField(null=True, blank=True)  # 🆕 new field

    def __str__(self): return f"{self.name} - {self.category.name}"

# ----------------- Contestant -----------------
class Contestant(models.Model):
    chest_no = models.PositiveIntegerField(unique=True, null=True)
    name = models.CharField(max_length=100)
    team = models.ForeignKey(Team, on_delete=models.CASCADE, null=True, blank=True)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, null=True)
    total_points = models.IntegerField(default=0)
    

    def __str__(self): return self.name

    def save(self, *args, **kwargs):
        if not self.chest_no:
            last = Contestant.objects.all().order_by('-chest_no').first()
            self.chest_no = 1020 if not last else last.chest_no + 1
        super().save(*args, **kwargs)
        
# ----------------- Participation -----------------
class Participation(models.Model):
    contestant = models.ForeignKey(Contestant, on_delete=models.CASCADE)
    program = models.ForeignKey(Program, on_delete=models.CASCADE)
    marks = models.IntegerField(null=True, blank=True)
    code_letter = models.CharField(max_length=2, null=True, blank=True)
    rank = models.PositiveIntegerField(null=True, blank=True)
    grade = models.CharField(max_length=1, null=True, blank=True)
    points_awarded = models.BooleanField(default=False)
    marks_added_at = models.DateTimeField(default=timezone.now, null=True, blank=True)
   
    def __str__(self):
        return f"{self.contestant.name} ({self.program.name})"    

# ----------------- Group Participation -----------------
class GroupParticipation(models.Model):
    program = models.ForeignKey(Program, on_delete=models.CASCADE)
    contestants = models.ManyToManyField(Contestant)
    team = models.ForeignKey(Team, on_delete=models.CASCADE, null=True, blank=True)  # All contestants should be from same team
    group_name = models.CharField(max_length=200, blank=True)  # Optional group name
    code_letter = models.CharField(max_length=5, null=True, blank=True)
    marks = models.IntegerField(null=True, blank=True)
    rank = models.PositiveIntegerField(null=True, blank=True)
    grade = models.CharField(max_length=1, null=True, blank=True)
    points_awarded = models.BooleanField(default=False)

    def __str__(self):
        contestant_names = ", ".join([c.name for c in self.contestants.all()])
        return f"{contestant_names} ({self.program.name})"

    def get_contestant_names(self):
        return ", ".join([contestant.name for contestant in self.contestants.all()])

    def save(self, *args, **kwargs):
        # Validate that the program is a group program
        if not self.program.is_group:
            raise ValueError("Cannot create group participation for non-group program")
        super().save(*args, **kwargs)

    def clean(self):
        from django.core.exceptions import ValidationError
        
        # Check if program is group program
        if not self.program.is_group:
            raise ValidationError("This program is not a group program")
        
        # Check participant count (this will be validated in views/forms)
        if hasattr(self, 'contestants'):
            count = self.contestants.count()
            if count < self.program.min_participants or count > self.program.max_participants:
                raise ValidationError(
                    f"Number of participants must be between {self.program.min_participants} "
                    f"and {self.program.max_participants}"
                )

# ----------------- Team Points -----------------
class TeamPoints(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    points = models.IntegerField(default=0)

# ----------------- Points Configuration -----------------
class PointsConfig(models.Model):
    """Configuration for points calculation"""
    # Rank-based points
    rank_1_points = models.IntegerField(default=10)
    rank_2_points = models.IntegerField(default=6)
    rank_3_points = models.IntegerField(default=3)
    
    # Grade-based points
    grade_a_points = models.IntegerField(default=10)
    grade_b_points = models.IntegerField(default=6)
    grade_c_points = models.IntegerField(default=3)
    
    # Grade thresholds
    grade_a_threshold = models.IntegerField(default=80)
    grade_b_threshold = models.IntegerField(default=70)
    grade_c_threshold = models.IntegerField(default=60)
    
    class Meta:
        # Ensure only one configuration exists
        verbose_name = "Points Configuration"
        verbose_name_plural = "Points Configuration"

    @classmethod
    def get_config(cls):
        """Get or create the points configuration"""
        config, created = cls.objects.get_or_create(id=1)
        return config

# ----------------- System Setting -----------------
class SystemSetting(models.Model):
    key = models.CharField(max_length=100, unique=True)
    value = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.key}: {self.value}"

    @classmethod
    def get_setting(cls, key, default=None):
        try:
            return cls.objects.get(key=key).value
        except cls.DoesNotExist:
            return default


# ----------------- Fest Days & Schedule -----------------
class FestDay(models.Model):
    day_number = models.PositiveIntegerField(unique=True)
    date = models.DateField(null=True, blank=True)
    name = models.CharField(max_length=100, blank=True)
    start_time = models.TimeField(default='09:00', help_text="Operating start time for this day")
    end_time = models.TimeField(default='21:00', help_text="Operating end time for this day")

    class Meta:
        ordering = ['day_number']

    def __str__(self):
        time_str = f"[{self.start_time.strftime('%I:%M %p')} - {self.end_time.strftime('%I:%M %p')}]"
        if self.name:
            return f"Day {self.day_number} ({self.name}) {time_str}"
        if self.date:
            return f"Day {self.day_number} - {self.date.strftime('%d %b %Y')} {time_str}"
        return f"Day {self.day_number} {time_str}"


class Stage(models.Model):
    STAGE_TYPES = (
        ('STAGE', 'Stage Venue'),
        ('OFF_STAGE', 'Off-Stage Venue'),
    )
    name = models.CharField(max_length=100)
    stage_type = models.CharField(max_length=15, choices=STAGE_TYPES, default='STAGE')
    location_details = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['stage_type', 'name']

    def __str__(self):
        return f"{self.name} [{self.get_stage_type_display()}]"


class ProgramSchedule(models.Model):
    program = models.OneToOneField(Program, on_delete=models.CASCADE, related_name='schedule')
    fest_day = models.ForeignKey(FestDay, on_delete=models.CASCADE, related_name='schedules')
    stage = models.ForeignKey(Stage, on_delete=models.CASCADE, related_name='schedules')
    start_time = models.TimeField()
    end_time = models.TimeField()
    total_duration_minutes = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['fest_day__day_number', 'start_time']

    def __str__(self):
        return f"{self.program.name} ({self.fest_day} @ {self.stage.name}: {self.start_time.strftime('%I:%M %p')} - {self.end_time.strftime('%I:%M %p')})"

