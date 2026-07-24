from .models import SystemSetting

def fest_settings(request):
    return {
        'fest_name': SystemSetting.get_setting('fest_name', 'Arts Fest'),
        'institution_name': SystemSetting.get_setting('institution_name', 'Campus / Institution'),
        'short_name': SystemSetting.get_setting('short_name', 'Fest Portal'),
        'youtube_embed_url': SystemSetting.get_setting('youtube_embed_url', ''),
    }
