from django.core.management.base import BaseCommand
from core.models import ProgramSchedule, Participation, GroupParticipation, Contestant, TeamPoints, Team, Program

class Command(BaseCommand):
    help = 'Reset all festival transactional data for setting up a new client festival'

    def add_arguments(self, parser):
        parser.add_argument(
            '--noinput', '--no-input',
            action='store_false',
            dest='interactive',
            help='Tells Django to NOT prompt the user for input of any kind.',
        )

    def handle(self, *args, **options):
        interactive = options.get('interactive', True)
        if interactive:
            confirm = input("Are you sure you want to delete all contestants, participations, scores, and schedules? (yes/no): ")
            if confirm.lower() not in ['yes', 'y']:
                self.stdout.write(self.style.WARNING("Data reset cancelled."))
                return

        Participation.objects.all().delete()
        GroupParticipation.objects.all().delete()
        Contestant.objects.all().delete()
        ProgramSchedule.objects.all().delete()
        TeamPoints.objects.all().delete()
        
        for team in Team.objects.all():
            team.total_points = 0
            team.save()

        Program.objects.update(is_announced=False, announced_at=None, result_number=None)

        self.stdout.write(self.style.SUCCESS("Successfully reset all festival transactional data for a new client!"))
