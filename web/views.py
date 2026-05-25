import json

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import redirect, render

VITE_ENTRY = 'src/main.tsx'


def _load_vite_manifest():
    manifest_path = settings.BASE_DIR / 'static' / 'frontend' / '.vite' / 'manifest.json'
    if not manifest_path.is_file():
        return None
    return json.loads(manifest_path.read_text(encoding='utf-8'))


def _vite_entry_assets():
    manifest = _load_vite_manifest()
    if not manifest:
        return None, []
    entry = manifest.get(VITE_ENTRY) or manifest.get('index.html')
    if not entry:
        return None, []
    js_file = entry.get('file')
    css_files = entry.get('css') or []
    if not js_file:
        return None, []
    return f'frontend/{js_file}', [f'frontend/{c}' for c in css_files]


def spa(request):
    if request.path.startswith('/manage'):
        next_url = request.get_full_path()
        return redirect(f'/manage/login/?next={next_url}')

    vite_js, vite_css = _vite_entry_assets()
    if not vite_js:
        return HttpResponse(
            '<h1>Frontend not built</h1>'
            '<p>Run build in mandeles-react-test5/mandeles-react then copy static/frontend</p>',
            status=503,
            content_type='text/html; charset=utf-8',
        )
    response = render(
        request,
        'web/spa.html',
        {
            'vite_js': vite_js,
            'vite_css': vite_css,
            'page_title': f'Mandeles.co.il v{settings.APP_VERSION}',
            'app_version': settings.APP_VERSION,
        },
    )
    if settings.DEBUG:
        response['Cache-Control'] = 'no-store, no-cache, must-revalidate'
        response['Pragma'] = 'no-cache'
    return response
