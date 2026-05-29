"""בדיקות תחקור בקשת שינוי AI – זיהוי הוספה/מחיקה/עריכה של קבצים."""
from django.test import SimpleTestCase

from ai_agent.models import AIChangeRequest
from ai_agent.services.diagnostics import build_request_diagnostics, classify_diff_files

MODIFY_DIFF = """diff --git a/static/css/portal.css b/static/css/portal.css
--- a/static/css/portal.css
+++ b/static/css/portal.css
@@ -1,3 +1,3 @@
 .a{color:red}
-.b{color:blue}
+.b{color:green}
"""

NEW_FILE_DIFF = """diff --git a/templates/web/new_page.html b/templates/web/new_page.html
new file mode 100644
--- /dev/null
+++ b/templates/web/new_page.html
@@ -0,0 +1,2 @@
+<h1>חדש</h1>
+<p>תוכן</p>
"""

DELETE_FILE_DIFF = """diff --git a/templates/web/old.html b/templates/web/old.html
deleted file mode 100644
--- a/templates/web/old.html
+++ /dev/null
@@ -1,2 +0,0 @@
-<h1>ישן</h1>
-<p>נמחק</p>
"""


class ClassifyDiffTests(SimpleTestCase):
    def test_modified_file(self):
        files = classify_diff_files(MODIFY_DIFF)
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0]['path'], 'static/css/portal.css')
        self.assertEqual(files[0]['kind'], 'modified')
        self.assertEqual(files[0]['added'], 1)
        self.assertEqual(files[0]['removed'], 1)

    def test_new_file_detected_as_added(self):
        files = classify_diff_files(NEW_FILE_DIFF)
        self.assertEqual(files[0]['kind'], 'added')
        self.assertEqual(files[0]['path'], 'templates/web/new_page.html')
        self.assertEqual(files[0]['added'], 2)

    def test_deleted_file_detected_as_deleted(self):
        files = classify_diff_files(DELETE_FILE_DIFF)
        self.assertEqual(files[0]['kind'], 'deleted')
        self.assertEqual(files[0]['path'], 'templates/web/old.html')

    def test_multi_file_counts(self):
        diff = NEW_FILE_DIFF + DELETE_FILE_DIFF + MODIFY_DIFF
        diag = build_request_diagnostics(
            AIChangeRequest(pk=1, prompt='בקשה', result=diff),
        )
        self.assertEqual(diag['counts']['added'], 1)
        self.assertEqual(diag['counts']['deleted'], 1)
        self.assertEqual(diag['counts']['modified'], 1)
        self.assertTrue(diag['has_diff'])

    def test_no_diff_falls_back_to_files_touched(self):
        diag = build_request_diagnostics(
            AIChangeRequest(pk=1, prompt='בקשה', files_touched=['templates/web/x.html']),
        )
        self.assertFalse(diag['has_diff'])
        self.assertEqual(diag['files'][0]['path'], 'templates/web/x.html')
