from .models import SystemSetting

def fest_settings(request):
    return {
        'fest_name': SystemSetting.get_setting('fest_name', 'Meelad Competition'),
    }
