import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import jobs

TABLE = '''<table><tr><td>Acme</td><td>SWE Intern</td><td>NYC<br>Remote</td><td><a href="https://example.com/a">Apply</a></td></tr>
<tr><td>↳</td><td>Data Intern</td><td>NYC</td><td><a href="https://example.com/b">Apply</a></td></tr>
<tr><td>Closed Co</td><td>SWE</td><td>NYC</td><td>🔒</td></tr></table>'''

class Tests(unittest.TestCase):
    def test_html_and_closed(self):
        parsed = jobs.parse_jobs(TABLE)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed['https://example.com/b']['company'], 'Acme')
        self.assertEqual(parsed['https://example.com/a']['location'], 'NYC, Remote')

    def test_markdown(self):
        parsed = jobs.parse_jobs('| Acme | SWE | NYC | [Apply](https://example.com/a) | Today |')
        self.assertEqual(parsed['https://example.com/a']['title'], 'SWE')

    def test_empty_source_fails(self):
        with self.assertRaises(ValueError):
            jobs.parse_jobs('Unexpected format')

    def test_baseline_then_new_only(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / 'seen_jobs.json'
            with patch.object(jobs, 'STATE', state), patch.dict('os.environ', {
                'INTERNSHIP_WEBHOOK': 'unused', 'NEW_GRAD_WEBHOOK': 'unused'
            }), patch.object(jobs, 'fetch', return_value=jobs.parse_jobs(TABLE)), patch.object(jobs, 'post') as post, patch.object(jobs.time, 'sleep'):
                jobs.main()
                post.assert_not_called()
                jobs.main()
                post.assert_not_called()
                data = json.loads(state.read_text())
                data['internships'].remove('https://example.com/b')
                state.write_text(json.dumps(data))
                jobs.main()
                self.assertEqual(post.call_count, 1)
                self.assertIn('https://example.com/b', json.loads(state.read_text())['internships'])

if __name__ == '__main__':
    unittest.main()
