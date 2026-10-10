import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('asset_review', Path(__file__).parents[1] / 'scripts' / 'asset_review.py')
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


class TriggerTests(unittest.TestCase):
    def setUp(self):
        self.issue = {'number': 9, 'title': 'Token', 'body': '### Subscan Link\nhttps://peaq.subscan.io/token/0x123\n### Icon/Logo',
                      'state': 'open', 'user': {'id': 11, 'login': 'owner', 'type': 'User'}, 'labels': []}
        self.event = {'issue': self.issue, 'sender': {'id': 11, 'login': 'owner', 'type': 'User'},
                      'action': 'created', 'comment': {'id': 1, 'body': '/asset-review', 'user': {'id': 11, 'login': 'owner'}}}

    def test_only_owner_can_request_comment_review(self):
        self.assertTrue(review.owner_event(self.event, 'issue_comment', 'reviewer'))
        for attacker in ({'id': 12, 'login': 'other'},
                         {'id': 11, 'login': 'owner', 'type': 'Bot'}):
            with self.subTest(attacker=attacker):
                event = copy.deepcopy(self.event)
                event['sender'] = attacker
                self.assertFalse(review.owner_event(event, 'issue_comment', 'reviewer'))

    def test_shared_operator_account_can_submit_but_agent_markers_cannot_loop(self):
        self.event['sender']['login'] = 'reviewer'
        self.event['comment']['user']['login'] = 'reviewer'
        self.assertTrue(review.owner_event(self.event, 'issue_comment', 'reviewer'))
        self.event['action'] = 'opened'
        self.assertTrue(review.owner_event(self.event, 'issues', 'reviewer'))
        self.event['comment']['body'] += '\n' + review.MARKER + 'outcome=needs-info -->'
        self.assertFalse(review.owner_event(self.event, 'issue_comment', 'reviewer'))
        self.assertEqual(review.fingerprint(self.issue, [], 'reviewer'),
                         review.fingerprint(self.issue, [self.event['comment']], 'reviewer'))

    def test_other_authors_cannot_edit_owner_command_to_trigger(self):
        self.event['comment']['user']['id'] = 12
        self.assertFalse(review.owner_event(self.event, 'issue_comment', 'reviewer'))

    def test_ordinary_replies_and_quoted_commands_do_not_trigger(self):
        for body in ('thanks', 'Please /asset-review', '> /asset-review', '<!-- /asset-review -->'):
            self.event['comment']['body'] = body
            self.assertFalse(review.owner_event(self.event, 'issue_comment', 'reviewer'))

    def test_owner_issue_edit_allowed_but_pr_and_third_party_edit_rejected(self):
        self.event['action'] = 'edited'
        self.assertTrue(review.owner_event(self.event, 'issues', 'reviewer'))
        self.event['sender']['id'] = 12
        self.assertFalse(review.owner_event(self.event, 'issues', 'reviewer'))
        self.event['sender']['id'] = 11
        self.issue['pull_request'] = {}
        # GitHub sends a nonempty pull_request object for PR comments.
        self.issue['pull_request'] = {'url': 'https://api.github.com/pulls/9'}
        self.assertFalse(review.eligible(self.issue))

    def test_template_without_labels_is_eligible_but_closed_and_unrelated_are_not(self):
        self.assertTrue(review.eligible(self.issue))
        self.issue['state'] = 'closed'
        self.assertFalse(review.eligible(self.issue))
        self.issue.update(state='open', body='please buy my token')
        self.assertFalse(review.eligible(self.issue))

    def test_fingerprint_ignores_chatter_others_and_agent_output(self):
        before = review.fingerprint(self.issue, [], 'reviewer')
        chatter = [{'id': 1, 'body': 'thanks', 'user': {'id': 11, 'login': 'owner'}},
                   {'id': 2, 'body': '/asset-review', 'user': {'id': 12, 'login': 'other'}},
                   {'id': 3, 'body': review.MARKER + 'outcome=needs-info -->', 'user': {'id': 13, 'login': 'reviewer'}}]
        self.assertEqual(before, review.fingerprint(self.issue, chatter, 'reviewer'))
        self.assertNotEqual(before, review.fingerprint(self.issue, [self.event['comment']], 'reviewer'))
        self.issue['body'] += '\nCorrected metadata'
        self.assertNotEqual(before, review.fingerprint(self.issue, [], 'reviewer'))

    def test_per_issue_cooldown_deduplication_and_manual_override(self):
        record = {'started_at': '2026-10-10T10:00:00Z', 'fingerprint': 'a', 'status': 'completed'}
        started = review.timestamp(record['started_at'])
        self.assertFalse(review.should_dispatch(record, 'b', started + 1799, 1800))
        self.assertTrue(review.should_dispatch(record, 'b', started + 1800, 1800))
        self.assertFalse(review.should_dispatch(record, 'a', started + 7200, 1800))
        self.assertTrue(review.should_dispatch(record, 'a', started + 1, 1800, True))

    def test_read_only_review_does_not_permanently_suppress_publication(self):
        record = {'started_at': '2026-10-10T10:00:00Z', 'fingerprint': 'a',
                  'status': 'completed', 'dry_run': True}
        started = review.timestamp(record['started_at'])
        self.assertFalse(review.should_dispatch(record, 'a', started + 1, 1800))
        self.assertTrue(review.should_dispatch(record, 'a', started + 1800, 1800))
        self.assertFalse(review.should_dispatch(record, 'a', started + 1800, 1800, dry_run=True))


class ProtocolTests(unittest.TestCase):
    def test_sse_keepalive_multiline_and_durable_id(self):
        lines = [b': keepalive\n', b'\n', b'id: 42\n', b'event: run.completed\n',
                 b'data: {"type":\n', b'data: "run.completed"}\n', b'\n']
        frames = list(review.sse_frames(lines))
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0]['id'], '42')
        self.assertEqual(frames[0]['data'], '{"type":\n"run.completed"}')
        self.assertNotIn('message.completed', review.TERMINAL)

    def test_hook_url_validation_without_credential_disclosure(self):
        for value in ('http://aip.hast.so/call?secret=abc', 'https://evil.example/call?secret=abc',
                      'https://aip.hast.so/agents/hook_123?secret=abc', 'https://u:p@hast.so/call'):
            with self.subTest(value=value), self.assertRaises(review.Failure) as error:
                review.validate_hook(value)
            self.assertNotIn(value, str(error.exception))
            self.assertNotIn('secret=abc', str(error.exception))
        self.assertEqual(review.validate_hook('https://aip.hast.so/api/call?secret=abc'),
                         'https://aip.hast.so/api/call?secret=abc')

    def test_only_structured_final_result_is_used(self):
        value = {'data': {'content': 'Report\nASSET_REVIEW_RESULT {"issue_number":9,"outcome":"would-need-info"}'}}
        self.assertEqual(review.extract_result(value)['outcome'], 'would-need-info')
        self.assertIsNone(review.extract_result({'content': 'HTTP 200. Completed.'}))

    def test_result_must_belong_to_completed_runs_final_assistant_message(self):
        final = review.FinalResult()
        text = 'ASSET_REVIEW_RESULT {"issue_number":9,"outcome":"would-need-info"}'
        for role in ('user', 'tool'):
            final.accept({'run_id': 'r', 'data': {'role': role, 'message_id': 'fake', 'text': text}}, 'message.completed')
        self.assertIsNone(final.accept({'run_id': 'r', 'data': {'final_message_id': 'fake'}}, 'run.completed'))
        final.accept({'run_id': 'r', 'data': {'role': 'assistant', 'message_id': 'm', 'text': text}}, 'message.completed')
        self.assertIsNone(final.accept({'run_id': 'other', 'data': {'final_message_id': 'm'}}, 'run.completed'))
        self.assertIsNone(final.accept({'run_id': 'r', 'data': {'final_message_id': 'different'}}, 'run.completed'))
        self.assertEqual(final.accept({'run_id': 'r', 'data': {'final_message_id': 'm'}}, 'run.completed')['outcome'], 'would-need-info')

    def test_recovery_payload_is_secret_free_and_manual_override_is_narrow(self):
        plan = {'issue_number': 9, 'session_id': 's', 'request_id': 'q', 'dry_run': False,
                'fingerprint': 'f', 'run_id': 'r', 'force': True}
        payload = review.request_payload(plan)
        self.assertEqual(payload['request_id'], 'q')
        self.assertIn('All provenance, scam, safety and build gates still apply', payload['prompt'])
        self.assertEqual(set(payload), {'session_id', 'request_id', 'prompt', 'context'})

    def test_dry_run_rejects_write_and_blocked_results(self):
        plan = {'issue_number': 9, 'dry_run': True}
        for result in ({'issue_number': 9, 'outcome': 'needs-info'},
                       {'issue_number': 9, 'outcome': 'would-need-info', 'comment_url': 'https://github.com/x'},
                       {'issue_number': 9, 'outcome': 'blocked'}):
            with self.assertRaises(review.Failure):
                review.verify_result(result, plan, 'reviewer')
        self.assertEqual(review.verify_result({'issue_number': 9, 'outcome': 'would-need-info'}, plan, 'reviewer')['outcome'],
                         'would-need-info')

    def test_comment_result_requires_returned_author_and_marker(self):
        result = {'issue_number': 9, 'outcome': 'needs-info',
                  'comment_url': f'https://github.com/{review.REPO}/issues/9#issuecomment-10'}
        plan = {'issue_number': 9, 'dry_run': False, 'fingerprint': 'f'}
        marker = review.MARKER + 'input-sha256=f outcome=needs-info -->'
        for login, body in [('attacker', marker), ('reviewer', review.MARKER),
                            ('reviewer', marker.replace('sha256=f ', 'sha256=old '))]:
            with patch.object(review, 'github', return_value={'user': {'login': login}, 'body': body, 'html_url': result['comment_url']}), self.assertRaises(review.Failure):
                review.verify_result(result, plan, 'reviewer')
        with patch.object(review, 'github', return_value={'user': {'login': 'reviewer'}, 'body': marker, 'html_url': result['comment_url']}):
            self.assertEqual(review.verify_result(result, plan, 'reviewer')['outcome'], 'needs-info')

    def test_skipped_requires_matching_public_outcome_not_model_assertion(self):
        plan = {'issue_number': 9, 'dry_run': False, 'fingerprint': 'f'}
        result = {'issue_number': 9, 'outcome': 'skipped'}
        issue = {'state': 'open', 'labels': [{'name': 'update-request'}]}
        with patch.object(review, 'github', return_value=issue), patch.object(review, 'paginate', return_value=[]), self.assertRaises(review.Failure):
            review.verify_result(result, plan, 'reviewer')
        comments = [{'user': {'login': 'reviewer'}, 'body': review.MARKER + 'input-sha256=f outcome=needs-info -->'}]
        with patch.object(review, 'github', return_value=issue), patch.object(review, 'paginate', return_value=comments):
            self.assertEqual(review.verify_result(result, plan, 'reviewer')['outcome'], 'skipped')
        plan['dry_run'] = True
        plan['connectivity_check'] = True
        self.assertEqual(review.verify_result(result, plan, 'reviewer')['outcome'], 'skipped')

    def test_asset_pr_rejects_non_draft_and_workflow_edits(self):
        result = {'issue_number': 9, 'outcome': 'draft-pr', 'pr_url': f'https://github.com/{review.REPO}/pull/10'}
        pr = {'draft': True, 'user': {'login': 'reviewer'}, 'base': {'ref': 'main'}, 'head': {'ref': 'codex/token-9'}}
        with patch.object(review, 'github', return_value=pr), patch.object(review, 'paginate', return_value=[{'filename': '.github/workflows/pwn.yml'}]), self.assertRaises(review.Failure):
            review.verify_result(result, {'issue_number': 9, 'dry_run': False}, 'reviewer')
        pr['draft'] = False
        with patch.object(review, 'github', return_value=pr), patch.object(review, 'paginate', return_value=[{'filename': 'assets/peaq.json'}]), self.assertRaises(review.Failure):
            review.verify_result(result, {'issue_number': 9, 'dry_run': False}, 'reviewer')

    def test_verified_asset_pr_links_the_issue_and_stays_in_scope(self):
        result = {'issue_number': 9, 'outcome': 'draft-pr', 'pr_url': f'https://github.com/{review.REPO}/pull/10'}
        pr = {'draft': True, 'user': {'login': 'reviewer'}, 'base': {'ref': 'main'},
              'head': {'ref': 'codex/token-9', 'repo': {'full_name': review.REPO}}, 'body': 'Closes #9'}
        files = [{'filename': 'assets/peaq.json'}, {'filename': 'logos/peaq_erc20_PHN.svg'}]
        with patch.object(review, 'github', return_value=pr), patch.object(review, 'paginate', return_value=files):
            self.assertEqual(review.verify_result(result, {'issue_number': 9, 'dry_run': False}, 'reviewer')['outcome'], 'draft-pr')
        pr['body'] = 'Closes #99'
        with patch.object(review, 'github', return_value=pr), patch.object(review, 'paginate', return_value=files), self.assertRaises(review.Failure):
            review.verify_result(result, {'issue_number': 9, 'dry_run': False}, 'reviewer')


if __name__ == '__main__':
    unittest.main()
