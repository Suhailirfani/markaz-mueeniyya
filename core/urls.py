# competition_app/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('', views.face_page, name='face_page'),
    path('auth/', views.landing_view, name='landing'),
    path('signup', views.signup_view, name='signup'),
    path('logout/', views.custom_logout_view, name='logout'),
    path('lock_user/<int:user_id>/', views.lock_user, name='lock_user'),
    path('unlock_user/<int:user_id>/', views.unlock_user, name='unlock_user'),
    path('admin_dashboard/', views.dashboard_admin, name='dashboard_admin'),
    path('team_dashboard/', views.dashboard_team, name='dashboard_team'),
    path('add_contestant/', views.add_contestant, name='add_contestant'),
    # path('assign_competition/', views.assign_competition, name='assign_competition'),
    path('assign/', views.assign_programs, name='assign_programs'),
    path('edit-programs/<int:contestant_id>/', views.edit_assigned_programs, name='edit_assigned_programs'),
    path('get-programs/', views.get_programs_for_contestant, name='get_programs_for_contestant'),
    path('get-contestants/', views.get_contestants, name='get_contestants'),
    path('add-group-program/', views.add_group_program, name='add_group_program'),
    path('assign-group-program/', views.assign_group_program, name='assign_group_program'),
    path('ajax/get-group-programs/', views.get_group_programs, name='get_group_programs'),
    path('ajax/get-participants/', views.get_participants_by_category, name='get_participants_by_category'),
    path('enter_marks_summary/', views.enter_marks_summary, name='enter_marks_summary'),
    path('results/', views.results_view, name='results'),
    path('export_excel/', views.export_excel, name='export_excel'),
    path('leaderboard/', views.leaderboard, name='leaderboard'),
    path('login/', views.custom_login_view, name='login'),
    path('admin/dashboard/', views.dashboard_admin, name='admin_dashboard'),
    path('team/dashboard/', views.dashboard_team, name='team_dashboard'),
    path('pending-users/', views.pending_users, name='pending_users'),
    path('approve-user/<int:user_id>/', views.approve_user, name='approve_user'),
    path('disapprove-user/<int:user_id>/', views.disapprove_user, name='disapprove_user'),
    path('users/', views.view_users, name='view_users'),
    path('users/delete/<int:user_id>/', views.delete_user, name='delete_user'),
    path('users/edit/<int:user_id>/', views.edit_user, name='edit_user'),
    path('add-category/', views.add_category, name='add_category'),
    path('edit-category/<int:category_id>/', views.edit_category, name='edit_category'),
    path('delete-category/<int:category_id>/', views.delete_category, name='delete_category'),
    path('add-program/', views.add_program, name='add_program'),
    path('edit-program/<int:program_id>/', views.edit_program, name='edit_program'),
    path('delete-program/<int:program_id>/', views.delete_program, name='delete_program'), 
    path('bulk-delete-programs/', views.bulk_delete_programs, name='bulk_delete_programs'),
    path('program_list/', views.program_list, name='program_list'),
    path('participants/', views.participant_list, name='participant_list'),
    path('participants/add/', views.add_participant, name='add_participant'),
    path('participants/edit/<int:id>/', views.edit_participant, name='edit_participant'),
    path('participants/delete/<int:id>/', views.delete_participant, name='delete_participant'),
    path('add_team/', views.add_team, name='add_team'),
    path('edit_team/<int:team_id>/', views.edit_team, name='edit_team'),
    path('delete_team/<int:team_id>/', views.delete_team, name='delete_team'),
    path('assigned-programs/', views.view_assigned_programs, name='assigned_programs'),
    path('download_participants_list/', views.download_participation_list_pdf, name='download_participation_list'),
    path('add_marks/', views.add_marks, name='add_marks'),
    path('undo-points/<int:participation_id>/', views.undo_points, name='undo_points'),
    path('recalculate-rankings/', views.recalculate_all_rankings, name='recalculate_rankings'),
    path('view_results/', views.view_results, name='view_results'),
    path('team-leaderboard/', views.team_leaderboard, name='team_leaderboard'),
    path('team-detail/<int:team_id>/', views.team_detail, name='team_detail'),
    path('team_marks_summary/', views.team_marks_summary, name='team_marks_summary'),
    path('download/pdf/', views.download_participants_pdf, name='download_participants_pdf'),
    path('api/programs-by-category/', views.get_programs_by_category, name='programs_by_category'), 
    path('participants/', views.participant_list, name='participant_list'),
    path('participants/category/', views.participants_by_category, name='participants_by_category'),
    path('participants/team/', views.participants_by_team, name='participants_by_team'),
    path('download/pdf/green_room_sign/<int:program_id>/', views.download_green_room_pdf, name='green_room_sign'),
    path('download/pdf/valuation_form/<int:program_id>/', views.download_valuation_form_pdf, name='valuation_form'),
    path('download/pdf/call_list/<int:program_id>/', views.download_call_list_pdf, name='call_list'),
    path('view/green_room/<int:program_id>/', views.green_room_list, name='green_room_list' ),
    path('download/pdf/all-call-list/', views.download_all_call_lists_pdf, name='download_all_call_list'),
    path('all-green-room-lists/', views.all_green_room_lists, name='all_green_room_lists'),
    path('download/all-valuation-forms/', views.download_all_valuation_forms_pdf, name='download_all_valuation_forms_pdf'),
    path('download/all-green-room-lists', views.download_all_green_room_pdf, name='download_all_green_room_pdf'),

    path('chest_number/', views.chest_number, name='chest_number'),
    # path('download-chest-cards/', views.download_chest_cards_pdf, name='download_chest_cards_pdf'),
    path('download/chest-cards/', views.download_chest_cards_pdf, name='download_chest_cards'),
    path('assigned-programs/pdf/', views.assigned_programs_pdf, name='assigned_programs_pdf'),
     # Group Program URLs
    path('group-participation/create/', views.create_group_participation, name='create_group_participation'),
    path('group-participation/', views.group_participation_list, name='group_participation_list'),
    path('group-participation/<int:group_id>/marks/', views.add_group_marks, name='add_group_marks'),
    
    # Program Results URLs
    path('program/<int:program_id>/results/', views.program_results, name='program_results'),
    
    # Leaderboard URLs
    path('leaderboard/', views.team_leaderboard2, name='team_leaderboard2'),
    path('leaderboard_cat/', views.leaderboard_cat, name='leaderboard_cat'),
    
    # Utility URLs
    path('recalculate-points/', views.recalculate_points_view, name='recalculate_points'),
    #result pdf 
    path('results/pdf/', views.results_pdf, name='results_pdf'),
    path('assigned-programs/delete/<int:participation_id>/', views.delete_assigned_program, name='delete_assigned_program'),

    # path('list_page/', views.list_page, name='list_page'),
    # urls.py
    path('program/<int:program_id>/toggle/', views.toggle_is_group, name='toggle_is_group'),
    path('contestant-points/', views.contestant_points_list, name='contestant_points_list'),
    path('results-page/', views.results_page, name='results_page'),
    # added on 26-09-25
    path('contestant-programs/', views.contestant_programs, name='contestant_programs'),
    path('contestant-programs-pdf/', views.contestant_programs_pdf_xml, name='contestant_programs_pdf'),
    path('enter-marks-sum-cat/', views.enter_marks_summary_cat, name='enter_marks_summary_cat'),
    path('program_result_pdf/<int:program_id>/', views.program_result_pdf, name='program_result_pdf'),


    


]