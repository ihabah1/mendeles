"""בדיקות פרשנות בקשות AI בשפה פשוטה."""
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from ai_agent.services.site_index import resolve_request, try_direct_edit


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
        self.assertIsNotNone(diff)
        self.assertIn('base_public.html', diff)
        self.assertIn('+      <span class="nav-greeting">{{ user.username }}</span>', diff)
        self.assertIn('-      <span class="nav-greeting">יופי {{ user.username }}</span>', diff)

    def test_add_page_with_api_intent(self):
        prompt = 'הוסף דף סטטיסטיקה שיציג נתונים מכתובת /api/stats'
        r = resolve_request(prompt, self.base)
        self.assertIn(r.intent, ('add_page', 'api_page'))
        self.assertTrue(r.target_files)
