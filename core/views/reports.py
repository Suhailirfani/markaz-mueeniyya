import io
import xlwt
from django.shortcuts import get_object_or_404, redirect
from django.http import HttpResponse
from django.template.loader import get_template
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from xhtml2pdf import pisa
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

from ..models import Program, Category, Team, Contestant, Participation
from .scoring import calculate_points, get_members_count_for_program

@login_required
def export_excel(request):
    is_admin = request.user.role == 'admin'

    participations = Participation.objects.filter(marks__isnull=False)
    if not is_admin:
        participations = participations.filter(program__is_announced=True)

    response = HttpResponse(content_type='application/ms-excel')
    response['Content-Disposition'] = 'attachment; filename="competition_results.xls"'

    wb = xlwt.Workbook(encoding='utf-8')
    ws = wb.add_sheet('Results')

    columns = ['Program', 'Contestant', 'Team', 'Marks', 'Grade', 'Rank']
    for col_num in range(len(columns)):
        ws.write(0, col_num, columns[col_num])

    rows = participations.values_list(
        'program__name', 'contestant__name', 'contestant__team__name',
        'marks', 'grade', 'rank'
    )
    for row_num, row in enumerate(rows, start=1):
        for col_num, value in enumerate(row):
            ws.write(row_num, col_num, value)

    wb.save(response)
    return response

@login_required
def download_participation_list_pdf(request):
    user = request.user
    participants = Contestant.objects.select_related(
        'team', 'category', 'participation__program'
    ).order_by('team__name', 'category__name', 'chest_no')

    if hasattr(user, 'team'):
        participants = participants.filter(team=user.team)

    filename = "participation_list.pdf"
    if hasattr(user, 'team'):
        filename = f"{user.team.name}_participation_list.pdf"

    context = {
        'fest_name': "MEELAD FEST",
        'date': timezone.now().strftime("%d-%m-%Y"),
        'participants': participants,
        'is_team_user': hasattr(user, 'team'),
        'team_name': user.team.name if hasattr(user, 'team') else None
    }

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
def download_participants_pdf(request):
    user = request.user
    participants = Contestant.objects.select_related('team', 'category').order_by('chest_no')

    if hasattr(user, 'team'):
        participants = participants.filter(team=user.team)
        filename = f"{user.team.name}_participants.pdf"
    else:
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

@login_required
def download_category_participants_pdf(request):
    user = request.user
    category_id = request.GET.get('category_id')
    participants = Contestant.objects.select_related('team', 'category').order_by('chest_no')

    if hasattr(user, 'team'):
        participants = participants.filter(team=user.team)

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

    if hasattr(user, 'team'):
        participants = participants.filter(team=user.team)
        filename = f"{user.team.name}_participants.pdf"
    else:
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
def download_green_room_pdf(request, program_id):
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
def download_call_list_pdf(request, program_id):
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

@login_required
def download_all_call_lists_pdf(request):
    user = request.user
    programs = Program.objects.all().order_by('name')

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

    if hasattr(user, 'team'):
        filename = f"all_programs_{user.team.name}_call_list.pdf"
    else:
        filename = "all_programs_call_list.pdf"

    template_path = 'all_call_list_pdf.html'
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

@login_required
def download_all_green_room_pdf(request):
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

    if hasattr(user, 'team'):
        filename = f"all_green_room_{user.team.name}.pdf"
    else:
        filename = "all_green_room.pdf"

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
    user = request.user
    programs = Program.objects.all().order_by('name')
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

    if hasattr(user, 'team'):
        filename = f"all_programs_{user.team.name}_valuation.pdf"
    else:
        filename = "all_programs_valuation.pdf"

    template_path = 'all_valuation_forms.html'
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

    template = get_template(template_path)
    html = template.render(context)

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="assigned_programs.pdf"'
    pisa.CreatePDF(io.BytesIO(html.encode("UTF-8")), dest=response, encoding='UTF-8')

    return response

@login_required
def contestant_programs_pdf_xml(request):
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

    template = get_template("contestant_programs_pdf_xml.html")
    html = template.render(context)

    result = io.BytesIO()
    pisa_status = pisa.CreatePDF(src=html, dest=result, encoding='utf-8')

    if pisa_status.err:
        return HttpResponse('We had some errors while generating PDF. Please check your template and CSS.')

    response = HttpResponse(result.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="contestant_programs.pdf"'
    return response

def render_to_pdf(template_src, context_dict={}):
    template = get_template(template_src)
    html = template.render(context_dict)
    response = HttpResponse(content_type='application/pdf')
    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('We had some errors <pre>' + html + '</pre>')
    return response

def results_pdf(request):
    is_admin = request.user.is_authenticated and request.user.role == 'admin'
    view_mode = request.GET.get('view', 'announced') if is_admin else 'announced'
    announced_only = (view_mode == 'announced')

    programs = Program.objects.filter(participation__marks__isnull=False).distinct()
    if announced_only:
        programs = programs.filter(is_announced=True)

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
                p.total_points = total_pts
            else:
                p.total_points = 0

        program_results.append({
            'program': program,
            'results': results,
        })

    context = {'program_results': program_results}
    return render_to_pdf('results_pdf.html', context)

def program_result_pdf(request, program_id):
    program = get_object_or_404(Program, id=program_id)

    # Restrict unannounced program PDFs to admin users only
    is_admin = request.user.is_authenticated and request.user.role == 'admin'
    if not program.is_announced and not is_admin:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("Results for this program are not yet announced.")

    results = (
        Participation.objects
        .filter(program=program, marks__isnull=False)
        .select_related('contestant', 'contestant__team')
        .order_by('rank')
    )

    members_count = get_members_count_for_program(program) if program.is_group else 1

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{program.name}_results.pdf"'

    doc = SimpleDocTemplate(response, pagesize=A4)
    styles = getSampleStyleSheet()
    normal = styles["Normal"]
    normal.wordWrap = 'CJK'

    elements = []

    title_style = styles['Title']
    elements.append(Paragraph("<font size=10 color='#033067'><b>HAYATHUL ISLAM MADRASA VETTIKKATTIRI</b></font>", title_style))
    elements.append(Paragraph("<font size=15 color='#d63384'><b>MEELAD FEST</b></font>", title_style))
    elements.append(Paragraph(f"<font size=14 color='#333333'><b>RESULTS: {program.name.upper()} - {program.category.name.upper()}</b></font>", title_style))
    elements.append(Spacer(1, 12))

    data = [["Rank", "Chest No", "Code Letter", "Name", "Team", "Grade", "Points"]]

    for r in results:
        rank_pts, grade_pts, total_pts = calculate_points(
            r.rank,
            r.grade,
            program.is_group,
            members_count
        )

        data.append([
            Paragraph(str(r.rank or "-"), normal),
            Paragraph(str(r.contestant.chest_no or "-"), normal),
            Paragraph(str(r.code_letter or "-"), normal),
            Paragraph(r.contestant.name.upper(), normal),
            Paragraph(r.contestant.team.name.upper() if r.contestant.team else "-", normal),
            Paragraph(str(r.grade or "-"), normal),
            Paragraph(f"{total_pts:.2f}", normal)
        ])

    table = Table(data, colWidths=[40, 50, 60, 140, 120, 50, 60])

    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))

    elements.append(table)
    elements.append(Spacer(1, 12))

    def add_watermark(canvas, doc):
        canvas.saveState()
        canvas.setFont('Helvetica-Bold', 60)
        canvas.setFillColorRGB(0.9, 0.9, 0.9, alpha=0.2)
        canvas.translate(300, 600)
        canvas.rotate(45)
        canvas.drawCentredString(0, 0, "MEELAD FEST")
        canvas.restoreState()

    doc.build(elements, onFirstPage=add_watermark, onLaterPages=add_watermark)
    return response

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
                contestant.team.name if contestant.team else "-",
                contestant.category.name if contestant.category else "-"
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

