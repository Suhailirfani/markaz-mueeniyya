from django.shortcuts import get_object_or_404, redirect, render
import pandas as pd
from .models import *
from django.contrib import messages
from django.contrib.auth.decorators import login_required

# Create your views here.
def girls_page(request):
    categories = CategoryOff.objects.all()
    programs = ProgramOff.objects.all()
    contestants = ContestantOff.objects.all()
    participations = Participation.objects.all()
    points_configuration = PointsConfig.objects.all()

    context = {
        'categories': categories,
        'programs':programs,
        'contestants':contestants,
        'participations':participations,
        'points_configuration':points_configuration,

    }
    return render(request, 'girls/girls_page.html', context)

def dashboard_off_campus(request):
    if request.user.role != 'off_campus': return redirect('dashboard_admin')
    off_campus = request.user.off_campus
    # In your view
    contestants = ContestantOff.objects.filter(off_campus=off_campus).order_by('category', 'name')

    context = {
        'off_campus':off_campus,
        'contestants':contestants,
    }
    return render(request, 'girls/dashboard_off_campus.html',context)

@login_required
def add_category_off(request):
    if not (request.user.is_superuser or request.user.role == 'admin'):
        return redirect('dashboard_off_campus')  # or wherever non-admins should go

    if request.method == 'POST':
        name = request.POST.get('name').strip()
        if name:
            if CategoryOff.objects.filter(name__iexact=name).exists():
                messages.warning(request, f"Category '{name}' already exists.")
            else:
                CategoryOff.objects.create(name=name)
                messages.success(request, f"Category '{name}' added successfully.")
                return redirect('add_category_off')
        else:
            messages.error(request, "Category name cannot be empty.")

    categories = CategoryOff.objects.all().order_by('name')
    return render(request, 'girls/add_category.html', {'categories': categories})

@login_required
def add_program_off(request):
    if not (request.user.is_superuser or request.user.role == 'admin'):
        return redirect('dashboard_team')

    categories = CategoryOff.objects.all()
    programs = ProgramOff.objects.all().order_by('-id')

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
                            category = CategoryOff.objects.get(name=category_name)
                            ProgramOff.objects.create(name=name, category=category)
                        except CategoryOff.DoesNotExist:
                            messages.warning(request, f"Category '{category_name}' not found for program '{name}'. Skipped.")
                messages.success(request, "Bulk upload completed successfully.")
            except Exception as e:
                messages.error(request, f"Error processing Excel file: {e}")

            return redirect('add_program_off')

        else:
            # Single entry form
            name = request.POST.get('name')
            category_id = request.POST.get('category')

            if name and category_id:
                category = CategoryOff.objects.get(id=category_id)
                ProgramOff.objects.create(name=name, category=category)
                messages.success(request, f"Program '{name}' added successfully under {category.name}.")
                return redirect('add_program_off')
            else:
                messages.error(request, "All fields are required.")

    return render(request, 'girls/add_program.html', {'categories': categories, 'programs': programs})

from django.http import JsonResponse

@login_required
def toggle_is_group(request, program_id):
    if not (request.user.is_superuser or request.user.role == 'admin'):
        return JsonResponse({'error': 'Permission denied'}, status=403)

    program = get_object_or_404(ProgramOff, id=program_id)
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

    program = get_object_or_404(ProgramOff, id=program_id)
    categories = CategoryOff.objects.all()

    if request.method == 'POST':
        name = request.POST.get('name').strip()
        category_id = request.POST.get('category')

        if name and category_id:
            category = get_object_or_404(CategoryOff, id=category_id)
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

    program = get_object_or_404(ProgramOff, id=program_id)
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
            ProgramOff.objects.filter(id__in=program_ids).delete()
            messages.success(request, f"{len(program_ids)} programs deleted successfully.")
        else:
            messages.warning(request, "No programs selected.")
        return redirect('add_program')

    # If GET request → show programs list with checkboxes
    programs = ProgramOff.objects.all().order_by('name')
    return render(request, "bulk_delete_programs.html", {"programs": programs})

def program_list(request):
    programs = ProgramOff.objects.all().order_by('category__name', 'name')
    categories = CategoryOff.objects.all()

    context = {
        'programs':programs,
        'categories': categories
    }
    return render(request, 'program_list.html', context)