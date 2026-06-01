"""הצגת אינדוקס תוכן האתר (למפת עריכה בשפה פשוטה)."""
from django.conf import settings
from django.core.management.base import BaseCommand

from admin_panel.ai_agent.services.site_index import format_index_summary, resolve_request


class Command(BaseCommand):
    help = 'בונה ומציג מפת תוכן האתר לבקשות שינוי AI'

    def add_arguments(self, parser):
        parser.add_argument(
            '--try',
            type=str,
            default='',
            help='נסח בקשה לדוגמה וראה פרשנות',
        )

    def handle(self, *args, **options):
        base = settings.BASE_DIR
        self.stdout.write(format_index_summary(base))
        if options['try']:
            r = resolve_request(options['try'], base)
            self.stdout.write(self.style.SUCCESS(f'\nפרשנות: {r.interpretation_he}'))
            self.stdout.write(f'פעולה: {r.action} | כוונה: {r.intent}')
            if r.replace_from:
                self.stdout.write(f'החלפה: «{r.replace_from}» → «{r.replace_to or "?"}»')
            self.stdout.write(f'קבצים: {", ".join(r.target_files[:5])}')
            direct = __import__(
                'ai_agent.services.site_index', fromlist=['try_direct_edit']
            ).try_direct_edit(options['try'], base, r)
            if direct:
                self.stdout.write(self.style.WARNING('ניתן לעריכה ישירה (ללא Gemini)'))
            for sn in r.matched_snippets[:5]:
                self.stdout.write(f'  {sn.file}:{sn.line} {sn.text[:50]}')
