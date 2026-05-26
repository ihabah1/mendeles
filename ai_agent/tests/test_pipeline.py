"""בדיקות שלבי תהליך שינוי AI."""
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from ai_agent.models import AIChangeRequest
from ai_agent.services.pipeline import build_pipeline


class PipelineStagesTests(SimpleTestCase):
    def _req(self, **kwargs):
        return AIChangeRequest(pk=1, prompt='בדיקה', **kwargs)

    def test_draft_only_first_stage_runnable(self):
        r = self._req(status=AIChangeRequest.Status.DRAFT)
        p = build_pipeline(r, jobs=[])
        stages = p['stages']
        self.assertFalse(stages[0]['done'])
        self.assertTrue(stages[0]['can_run'])
        self.assertFalse(stages[1]['can_run'])
        self.assertFalse(stages[2]['can_run'])

    def test_diff_ready_enables_pr_stage(self):
        r = self._req(
            status=AIChangeRequest.Status.DIFF_READY,
            result='diff --git a/x b/x',
        )
        p = build_pipeline(r, jobs=[])
        self.assertTrue(p['stages'][0]['done'])
        self.assertTrue(p['stages'][1]['can_run'])

    def test_pr_created_enables_merge(self):
        r = self._req(
            status=AIChangeRequest.Status.PR_CREATED,
            result='diff',
            pr_number=42,
        )
        p = build_pipeline(r, jobs=[])
        self.assertTrue(p['stages'][1]['done'])
        self.assertTrue(p['stages'][2]['can_run'])

    def test_merged_all_done(self):
        r = self._req(status=AIChangeRequest.Status.PR_MERGED, result='d', pr_number=1)
        p = build_pipeline(r, jobs=[])
        self.assertTrue(p['all_done'])
        for s in p['stages']:
            self.assertTrue(s['done'])
            self.assertFalse(s['can_run'])

    def test_incomplete_can_archive(self):
        from ai_agent.services.pipeline import can_archive_request

        r = self._req(status=AIChangeRequest.Status.DIFF_READY, result='diff')
        self.assertTrue(can_archive_request(r, jobs=[]))

    def test_merged_cannot_archive(self):
        from ai_agent.services.pipeline import can_archive_request

        r = self._req(status=AIChangeRequest.Status.PR_MERGED, result='d', pr_number=1)
        self.assertFalse(can_archive_request(r, jobs=[]))
