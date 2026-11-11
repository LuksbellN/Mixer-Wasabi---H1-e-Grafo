"""Paginação real em diretório temporário, substituindo apenas a rede."""
import tempfile
from pathlib import Path
import unittest
from collect import collect_address


def page(ids, total=None):
    result = {'txs': [{'hash': h, 'time': 1, 'inputs': [], 'out': []} for h in ids]}
    if total is not None:
        result['n_tx'] = total
    return result


class CollectionTests(unittest.TestCase):
    def test_pagination_resume_and_final_short_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            responses = {0: page(['a', 'b'], 3), 2: page(['c'], 3)}

            def fetch(a, offset, limit):
                if a != 'A' or limit != 2:
                    raise AssertionError('Wrong request')
                return responses.pop(offset)

            result = collect_address('A', root, fetch, page_size=2)
            self.assertEqual(result['status'], 'complete')
            self.assertEqual(result['unique_transactions'], 3)
            self.assertEqual(len(list((root/'A').glob('page_*.json'))), 2)
            # Resume must work without any response still available.
            resumed = collect_address('A', root, fetch, page_size=2)
            self.assertEqual(resumed['unique_transactions'], 3)

    def test_partial_failure_resumes_from_cached_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def failing(a, offset, limit):
                if offset == 0:
                    return page(['a', 'b'], 3)
                raise OSError('offline')

            result = collect_address('A', root, failing, page_size=2)
            self.assertEqual(result['status'], 'error')
            self.assertEqual(result['unique_transactions'], 2)

            def resumed(a, offset, limit):
                if offset != 2:
                    raise AssertionError('Downloaded cached page again')
                return page(['c'], 3)

            result = collect_address('A', root, resumed, page_size=2)
            self.assertEqual(result['status'], 'complete')
            self.assertEqual(result['unique_transactions'], 3)

    def test_repeated_page_not_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = collect_address('A', Path(tmp), lambda *a: page(['a', 'b']), page_size=2)
            self.assertEqual(result['status'], 'error')
            self.assertIn('repetida', result['error'])

    def test_empty_history_is_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = collect_address('A', Path(tmp), lambda *a: page([], 0))
            self.assertEqual(result['status'], 'complete')
            self.assertEqual(result['unique_transactions'], 0)

    def test_error_payload_is_not_empty_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = collect_address('A', Path(tmp), lambda *a: {'error': 'unavailable'})
            self.assertEqual(result['status'], 'error')

    def test_total_mismatch_is_not_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = collect_address('A', Path(tmp), lambda *a: page(['a'], 8))
            self.assertEqual(result['status'], 'error')
            self.assertIn('total', result['error'])


if __name__ == '__main__':
    unittest.main()
