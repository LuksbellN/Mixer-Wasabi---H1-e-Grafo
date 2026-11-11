"""Reconferência independente nos dados-fonte e nos grafos exportados."""
from collections import Counter
import csv
import hashlib
import json
import tarfile

import networkx as nx

from analyze import ROOT, save_json, utc


def csv_rows(name):
    with (ROOT/'results'/name).open(encoding='utf-8-sig') as stream:
        return list(csv.DictReader(stream))


def main():
    manifest = json.loads((ROOT/'data/manifest.json').read_text(encoding='utf-8'))
    summary = json.loads((ROOT/'results/summary.json').read_text(encoding='utf-8'))
    mixers = set(manifest['mixers'])
    seeds = set(manifest['seed_addresses'])
    raw_selected = []
    supplied = []
    archive = ROOT.parent/'wasabiTxs.tgz'
    with archive.open('rb') as f:
        assert hashlib.file_digest(f, 'sha256').hexdigest() == manifest['archive_sha256']
    with tarfile.open(archive, 'r:gz') as tar:
        for member in tar:
            if member.isfile():
                supplied.append(json.load(tar.extractfile(member)))
    assert {t['hash'] for t in supplied} == mixers
    supplied.sort(key=lambda t: (t['time'], t['hash']))
    selection = manifest['selection']
    raw_selected = supplied[selection['part']::selection['parts']][:selection['count']]
    assert [t['hash'] for t in raw_selected] == [t['txid'] for t in manifest['selected']]
    expected_seeds = {i['prev_out']['addr'] for t in raw_selected for i in t['inputs']}
    assert expected_seeds == seeds
    assert summary['coverage']['complete'] == len(seeds), 'Coleta ainda incompleta'
    assert summary['coverage']['errors'] == summary['coverage']['not_attempted'] == 0
    raw = list(raw_selected)
    page_count = 0
    for address in sorted(seeds):
        folder = ROOT/'data/cache'/summary['provider']/address
        state = json.loads((folder/'status.json').read_text(encoding='utf-8'))
        assert state['status'] == 'complete'
        pages = sorted(folder.glob('page_*.json'))
        seen = set()
        for index, page in enumerate(pages):
            env = json.loads(page.read_text(encoding='utf-8'))
            response = env['response']
            rows = response.get('txs', response.get('transactions'))
            assert env['offset'] == index*env['limit']
            assert len(rows) == env['limit'] or index == len(pages) - 1
            ids = [t.get('hash', t.get('txId')) for t in rows]
            assert not seen.intersection(ids)
            assert len(ids) == len(set(ids))
            seen.update(ids)
            assert response.get('n_tx', len(seen)) >= len(seen)
            raw.extend(rows)
            page_count += 1
        assert len(rows) < env['limit']
        assert len(seen) == state['unique_transactions']
        if 'n_tx' in response:
            assert len(seen) == response['n_tx']
        required_mixers = {t['hash'] for t in raw_selected
                           if any(i['prev_out'].get('addr') == address for i in t['inputs'])}
        assert required_mixers.issubset(seen), 'Histórico não contém mixer selecionado esperado'
    # Parse the two source formats here, without the production normalizer.
    canonical = {}
    for tx in raw:
        h = tx.get('hash', tx.get('txId'))
        ins = []
        for item in tx['inputs']:
            if item.get('coinbase') is True or ('prev_out' not in item and 'value' not in item):
                continue
            prev = item.get('prev_out', item)
            ins.append((prev.get('addr', prev.get('address')), prev['value']))
        outs = [(o.get('addr', o.get('address')), o['value']) for o in tx.get('out', tx.get('outputs'))]
        material = (tx['time'], tuple(ins), tuple(outs))
        if h in canonical:
            assert canonical[h] == material
        canonical[h] = material
    independent = nx.Graph()
    independent.add_nodes_from(seeds)
    expected_edges = Counter()
    for h, (ts, ins, outs) in canonical.items():
        ia = sorted({a for a, _ in ins if a})
        oa = sorted({a for a, _ in outs if a})
        independent.add_nodes_from(ia + oa)
        if h not in mixers and len(ia) > 1:
            independent.add_edges_from((ia[0], a) for a in ia[1:])
        expected_edges.update((a, b, h) for a in ia for b in oa)
    exported = csv_rows('address_to_cluster.csv')
    mapping = {r['address']: r['cluster'] for r in exported}
    partition = {}
    for a, cid in mapping.items():
        partition.setdefault(cid, set()).add(a)
    expected_partition = {frozenset(c) for c in nx.connected_components(independent)}
    assert expected_partition == {frozenset(c) for c in partition.values()}
    before = csv_rows('edges_before.csv')
    after = csv_rows('edges_after.csv')
    assert Counter((e['source'], e['target'], e['txid']) for e in before) == expected_edges
    assert Counter((e['input_address'], e['output_address'], e['txid']) for e in after) == expected_edges
    assert all(e['source'] == mapping[e['input_address']] and
               e['target'] == mapping[e['output_address']] for e in after)
    assert len(before) == len(after) == summary['graph']['relations']
    assert not mixers.intersection(e['txid'] for e in csv_rows('h1_evidence.csv'))
    for name, vertices, edge_rows in [('before_addresses.graphml', len(mapping), before),
                                      ('after_h1.graphml', len(partition), after)]:
        graph = nx.read_graphml(ROOT/'results'/name, force_multigraph=True)
        assert len(graph) == vertices
        assert graph.number_of_edges() == len(before)
        actual = Counter((a, b, d['txid'], d['input_address'], d['output_address'])
                         for a, b, d in graph.edges(data=True))
        expected = Counter((e['source'], e['target'], e['txid'],
                            e['input_address'], e['output_address']) for e in edge_rows)
        assert actual == expected
        assert all(d['known_mixer'] == (d['txid'] in mixers) for _, _, d in graph.edges(data=True))
    pages = json.loads((ROOT/'results/source_pages.json').read_text(encoding='utf-8'))
    for item in pages:
        assert hashlib.sha256((ROOT/item['path']).read_bytes()).hexdigest() == item['sha256']
    assert len(canonical) == summary['transactions']['unique']
    assert len(mapping) == summary['graph']['addresses']
    assert len(partition) == summary['graph']['clusters']
    result = {'verified_utc': utc(), 'status': 'passed',
              'checks': ['archive_sha256', 'selection_and_all_inputs', 'all_histories_complete',
                         'pagination_and_provider_totals', 'selected_mixers_present_in_histories',
                         'source_copy_consistency',
                         'independent_networkx_h1_partition', 'mixer_exclusion',
                         'exact_payment_relation_multiset', 'contraction_multiplicity',
                         'graphml_counts_and_relations', 'cached_page_hashes'],
              'addresses_collected': len(seeds), 'pages': page_count,
              'transactions': len(canonical), 'vertices_before': len(mapping),
              'vertices_after': len(partition), 'relations_each_graph': len(before),
              'first_selected_tx_checked_in_archive': raw_selected[0]['hash']}
    example_file = ROOT/'results/example.json'
    if example_file.exists():
        example = json.loads(example_file.read_text(encoding='utf-8'))
        assert example['txid'] in canonical and example['txid'] not in mixers
        result['example_checked_in_cached_source'] = example['txid']
    save_json(ROOT/'results/verification.json', result)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
