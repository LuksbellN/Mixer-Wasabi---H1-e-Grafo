"""Exemplos sintéticos: valores esperados calculados à mão."""
import unittest
import json
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET
from analyze import normalize, deduplicate, cluster, relations


def raw(h, ins, outs, time=1):
    return {'hash': h, 'time': time,
            'inputs': [{'prev_out': {'addr': a, 'value': v}} for a, v in ins],
            'out': [{'addr': a, 'value': v} for a, v in outs]}


class AnalysisTests(unittest.TestCase):
    def test_equivalent_provider_schemas(self):
        a = raw('t1', [('A', 10), ('B', 20)], [('C', 29)])
        b = {'txId': 't1', 'time': 1,
             'inputs': [{'address': 'A', 'value': 10}, {'address': 'B', 'value': 20}],
             'outputs': [{'address': 'C', 'value': 29}]}
        self.assertEqual(normalize(a), normalize(b))

    def test_transitivity_and_mixer_exclusion_and_singleton(self):
        txs = [normalize(raw('t1', [('A', 5), ('B', 6)], [('X', 10)])),
               normalize(raw('t2', [('B', 4), ('C', 4)], [('Y', 7)])),
               normalize(raw('mixer_outside_subset', [('C', 4), ('D', 4)], [('Z', 7)]))]
        mapping, evidence = cluster(txs, {'mixer_outside_subset'}, {'E'})
        self.assertEqual(mapping['A'], mapping['C'])
        self.assertNotEqual(mapping['A'], mapping['D'])
        self.assertNotEqual(mapping['E'], mapping['A'])
        self.assertNotEqual(mapping['X'], mapping['A'])
        self.assertEqual([e['txid'] for e in evidence], ['t1', 't2'])

    def test_contraction_preserves_relations_and_loops(self):
        txs = [normalize(raw('t1', [('A', 5), ('B', 5)], [('A', 3), ('X', 6)]))]
        mapping, _ = cluster(txs, set(), set())
        before = list(relations(txs))
        after = list(relations(txs, mapping))
        self.assertEqual(len(before), 4)
        self.assertEqual(len(after), 4)
        self.assertEqual(sum(e['source'] == e['target'] for e in after), 2)
        self.assertEqual({e['txid'] for e in after}, {'t1'})

    def test_same_address_outputs_project_once(self):
        txs = [normalize(raw('t', [('A', 5)], [('B', 2), ('B', 2)]))]
        self.assertEqual(len(list(relations(txs))), 1)

    def test_deduplication_rejects_conflicting_values(self):
        a = normalize(raw('t1', [('A', 10)], [('B', 9)]))
        b = normalize(raw('t1', [('A', 10)], [('B', 8)]))
        with self.assertRaisesRegex(ValueError, 'conflit'):
            deduplicate([a, b])
        self.assertEqual(len(deduplicate([a, a])), 1)

    def test_missing_address_counted_not_invented(self):
        tx = normalize({'hash': 't', 'time': 1,
                        'inputs': [{'prev_out': {'value': 10}}],
                        'out': [{'addr': 'B', 'value': 9}]})
        self.assertEqual(tx['missing_inputs'], 1)
        self.assertEqual(list(relations([tx])), [])

    def test_gateway_missing_address_is_not_coinbase(self):
        tx = normalize({'txId': 'ordinary', 'time': 1,
                        'inputs': [{'coinbase': False, 'sigscript': '00', 'value': 10}],
                        'outputs': [{'address': 'B', 'value': 9}]})
        self.assertFalse(tx['coinbase'])
        self.assertEqual(tx['missing_inputs'], 1)

    def test_coinbase_script_has_no_previous_output(self):
        tx = normalize({'hash': 'coinbase', 'time': 1,
                        'inputs': [{'script': '03abcdef', 'sequence': 4294967295}],
                        'out': [{'addr': 'miner', 'value': 50}]})
        self.assertTrue(tx['coinbase'])
        self.assertEqual(tx['inputs'], [])

    def test_missing_transaction_fields_rejected(self):
        with self.assertRaises(ValueError):
            normalize({'hash': 'oops', 'inputs': [], 'out': []})

    def test_full_export_conserves_edges_and_excludes_known_mixer(self):
        from analyze import run, save_json
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mix = normalize(raw('mix', [('A', 10), ('C', 10)], [('Z', 19)]))
            manifest = {'seed_addresses': ['A', 'C'], 'selected': [mix],
                        'mixers': ['mix'], 'archive_sha256': 'fixture',
                        'total_transactions': 1, 'total_unique_input_addresses': 2,
                        'selection': {'count': 1}, 'selected_input_occurrences': 2}
            save_json(root/'data/manifest.json', manifest)
            hist = raw('t1', [('A', 3), ('B', 3)], [('A', 5)])
            save_json(root/'data/cache/rawaddr/A/page_00000000.json',
                      {'address': 'A', 'offset': 0, 'limit': 50,
                       'collected_utc': '2026-11-11T00:00:00+00:00',
                       'response': {'txs': [hist], 'n_tx': 1}})
            save_json(root/'data/cache/rawaddr/A/status.json',
                      {'address': 'A', 'status': 'complete', 'pages': 1,
                       'unique_transactions': 1, 'error': None})
            summary = run(root)
            self.assertEqual(summary['coverage']['complete'], 1)
            self.assertEqual(summary['coverage']['not_attempted'], 1)
            self.assertEqual(summary['graph']['addresses'], 4)
            self.assertEqual(summary['graph']['clusters'], 3)
            self.assertEqual(summary['graph']['relations'], 4)
            self.assertEqual(summary['graph']['cluster_loops'], 2)
            self.assertEqual(summary['h1']['excluded_known_mixers'], 1)
            ns = {'g': 'http://graphml.graphdrawing.org/xmlns'}
            graph = ET.parse(root/'results/after_h1.graphml')
            self.assertEqual(len(graph.findall('.//g:edge', ns)), 4)


if __name__ == '__main__':
    unittest.main()
