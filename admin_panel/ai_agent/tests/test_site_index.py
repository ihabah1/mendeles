"""בדיקות פרשנות בקשות AI בשפה פשוטה."""
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from admin_panel.ai_agent.services.site_index import resolve_request, try_direct_edit
from admin_panel.ai_agent.services.ui_registry import (
    apply_vision_to_resolved,
    build_ui_registry,
    match_labels_to_elements,
)


class SiteIndexInterpretationTests(SimpleTestCase):
    def setUp(self):
        self.base = Path(settings.BASE_DIR)

    def test_yofi_to_username_replace(self):
        prompt = 'במקום המילה יופי שיופיע שם משתמש'
        r = resolve_request(prompt, self.base)
        self.assertEqual(r.action, 'replace')
        self.assertEqual(r.replace_from, 'יופי')
        self.assertIn('user.username', r.replace_to)
        self.assertIn('templates/web/base_public.html', r.target_files[0])
        diff = try_direct_edit(prompt, self.base, r)
        if diff:
            self.assertIn('base_public.html', diff)
            self.assertNotIn('יופי', diff.split('+++ b/')[-1] if '+++ b/' in diff else '')
        else:
            path = self.base / 'templates/web/base_public.html'
            text = path.read_text(encoding='utf-8')
            self.assertNotIn('יופי', text)
            self.assertIn('display_name', text)

    def test_add_page_with_api_intent(self):
        prompt = 'הוסף דף סטטיסטיקה שיציג נתונים מכתובת /api/stats'
        r = resolve_request(prompt, self.base)
        self.assertIn(r.intent, ('add_page', 'api_page'))
        self.assertTrue(r.target_files)

    def test_ui_registry_maps_dashboard_sidebar(self):
        registry = build_ui_registry(self.base)
        labels = {e.label for e in registry}
        self.assertIn('דשבורד', labels)
        matched = match_labels_to_elements(['דשבורד', 'ראשי'], registry)
        dash = [e for e in matched if e.label == 'דשבורד']
        self.assertEqual(len(dash), 1)
        self.assertEqual(
            dash[0].file.replace('\\', '/'),
            'templates/portal/base_dashboard.html',
        )
        r = resolve_request('שנה את צבע הטקסט', self.base)
        enriched = apply_vision_to_resolved(r, ['דשבורד'], dash)
        self.assertIn('VISION / SCREENSHOT', enriched.enriched_prompt)
        self.assertIn('base_dashboard.html', enriched.target_files[0])
