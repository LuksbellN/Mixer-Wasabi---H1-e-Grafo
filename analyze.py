"""Leitura das transações, agrupamento H1 e exportação dos grafos."""
import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parent


def utc():
    return datetime.now(timezone.utc).isoformat()


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def write_csv(path, fields, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def normalize(tx):
    """Coloca os dois formatos do Blockchain.com no mesmo formato."""
    txid = tx.get('hash') or tx.get('txId')
    outputs = tx.get('out', tx.get('outputs'))
    if not txid or not isinstance(tx.get('inputs'), list) or not isinstance(outputs, list):
        raise ValueError('Transação sem hash/entradas/saídas válidos')
    if not isinstance(tx.get('time'), int):
        raise ValueError('Transação sem timestamp inteiro')
    ins, outs = [], []
    coinbase = False
    for item in tx['inputs']:
        if item.get('coinbase') is True or ('coinbase' not in item and
                'prev_out' not in item and 'value' not in item and 'script' in item):
            coinbase = True
            continue
        prev = item.get('prev_out', item)
        value = prev.get('value')
        if type(value) is not int or value < 0:
            raise ValueError(f'Valor de entrada inválido: {txid}')
        ins.append({'address': prev.get('addr', prev.get('address')), 'value': value})
    for item in outputs:
        value = item.get('value')
        if type(value) is not int or value < 0:
            raise ValueError(f'Valor de saída inválido: {txid}')
        outs.append({'address': item.get('addr', item.get('address')), 'value': value})
    return {'txid': txid, 'time': tx['time'], 'inputs': ins, 'outputs': outs,
            'coinbase': coinbase,
            'missing_inputs': sum(i['address'] is None for i in ins),
            'missing_outputs': sum(o['address'] is None for o in outs)}


def deduplicate(txs):
    found = {}
    for tx in txs:
        old = found.get(tx['txid'])
        if old is not None and old != tx:
            raise ValueError(f'Cópias conflitantes da transação {tx["txid"]}')
        found[tx['txid']] = tx
    return [found[h] for h in sorted(found)]


def addresses(tx, side):
    return sorted({i['address'] for i in tx[side] if i['address']})


def cluster(txs, mixers, seeds):
    parent = {a: a for a in seeds}

    def find(a):
        parent.setdefault(a, a)
        root = a
        while parent[root] != root:
            root = parent[root]
        while a != root:
            previous = parent[a]
            parent[a] = root
            a = previous
        return root

    evidence = []
    for tx in sorted(txs, key=lambda t: t['txid']):
        for a in addresses(tx, 'inputs') + addresses(tx, 'outputs'):
            find(a)
        if tx['txid'] in mixers or tx['coinbase']:
            continue
        ins = addresses(tx, 'inputs')
        if len(ins) > 1:
            merges = 0
            for a in ins[1:]:
                first, other = find(ins[0]), find(a)
                if first != other:
                    parent[other] = first
                    merges += 1
            evidence.append({'txid': tx['txid'], 'input_addresses': ins,
                             'new_unions': merges, 'time': tx['time']})
    groups = defaultdict(list)
    for a in sorted(parent):
        groups[find(a)].append(a)
    mapping = {}
    for members in groups.values():
        cid = 'H1_' + hashlib.sha256('\n'.join(members).encode()).hexdigest()[:20]
        for a in members:
            mapping[a] = cid
    return mapping, evidence


def relations(txs, mapping=None):
    """Uma relação por (tx, endereço de entrada, endereço de saída), sem BTC."""
    for tx in sorted(txs, key=lambda t: t['txid']):
        for a in addresses(tx, 'inputs'):
            for b in addresses(tx, 'outputs'):
                yield {'source': mapping[a] if mapping is not None else a,
                       'target': mapping[b] if mapping is not None else b,
                       'txid': tx['txid'], 'time': tx['time'],
                       'input_address': a, 'output_address': b}


def select(archive, count=10, part=0, parts=1):
    if count < 1 or parts < 1 or not 0 <= part < parts:
        raise ValueError('Quantidade/partição inválida')
    all_txs = []
    with tarfile.open(archive, 'r:gz') as tar:
        for member in tar:
            if member.isfile():
                all_txs.append(normalize(json.load(tar.extractfile(member))))
    all_txs = sorted(deduplicate(all_txs), key=lambda t: (t['time'], t['txid']))
    selected = all_txs[part::parts][:count]
    seeds = sorted({a for tx in selected for a in addresses(tx, 'inputs')})
    with open(archive, 'rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    return {'created_utc': utc(), 'archive_name': Path(archive).name,
            'archive_sha256': digest, 'total_transactions': len(all_txs),
            'total_inputs': sum(len(t['inputs']) for t in all_txs),
            'total_unique_input_addresses': len({a for t in all_txs for a in addresses(t, 'inputs')}),
            'selection': {'order': 'time,txid', 'count': count, 'part': part, 'parts': parts},
            'mixers': sorted(t['txid'] for t in all_txs),
            'selected': selected, 'seed_addresses': seeds,
            'selected_input_occurrences': sum(len(t['inputs']) for t in selected)}


def prepare(args):
    manifest = select(args.archive, args.count, args.part, args.parts)
    save_json(ROOT/'data/manifest.json', manifest)
    write_csv(ROOT/'results/selected_transactions.csv',
              ['txid', 'time_utc', 'inputs', 'unique_input_addresses', 'outputs'],
              ({'txid': t['txid'], 'time_utc': datetime.fromtimestamp(t['time'], timezone.utc).isoformat(),
                'inputs': len(t['inputs']), 'unique_input_addresses': len(addresses(t, 'inputs')),
                'outputs': len(t['outputs'])} for t in manifest['selected']))
    write_csv(ROOT/'results/seed_addresses.csv', ['address'],
              ({'address': a} for a in manifest['seed_addresses']))
    print(json.dumps({k: v for k, v in manifest.items()
                      if k not in {'selected', 'mixers', 'seed_addresses'}}, indent=2))
    print('selected:', len(manifest['selected']), 'addresses:', len(manifest['seed_addresses']))


def graphml(path, nodes, txs, mixers, mapping=None):
    """MultiDiGraph mantém pagamentos repetidos entre o mesmo par de vértices."""
    import networkx as nx

    graph = nx.MultiDiGraph()
    graph.add_nodes_from(sorted(nodes.items()))
    for i, edge in enumerate(relations(txs, mapping)):
        attrs = {k: v for k, v in edge.items() if k not in {'source', 'target'}}
        attrs['known_mixer'] = edge['txid'] in mixers
        graph.add_edge(edge['source'], edge['target'], key=f'e{i}', **attrs)
    nx.write_graphml(graph, path, encoding='utf-8')


def run(root=ROOT, provider='rawaddr'):
    root = Path(root)
    out = root/'results'
    out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((root/'data/manifest.json').read_text(encoding='utf-8'))
    seeds, mixers = set(manifest['seed_addresses']), set(manifest['mixers'])
    txs = list(manifest['selected'])
    provenance, states, sources = [], [], []
    collected_times = []
    for tx in txs:
        provenance.append({'txid': tx['txid'], 'source': 'wasabiTxs.tgz',
                           'address': '', 'offset': ''})
    for address in sorted(seeds):
        folder = root/'data/cache'/provider/address
        status = folder/'status.json'
        state = json.loads(status.read_text(encoding='utf-8')) if status.exists() else {
            'address': address, 'status': 'not_attempted', 'pages': 0,
            'unique_transactions': 0, 'error': 'Sem coleta'}
        states.append(state)
        for page in sorted(folder.glob('page_*.json')):
            env = json.loads(page.read_text(encoding='utf-8'))
            data = env['response']
            raw_txs = data.get('txs', data.get('transactions'))
            if not isinstance(raw_txs, list) or env['address'] != address:
                raise ValueError('Página de histórico inválida')
            collected_times.append(env['collected_utc'])
            with page.open('rb') as f:
                digest = hashlib.file_digest(f, 'sha256').hexdigest()
            sources.append({'path': page.relative_to(root).as_posix(), 'sha256': digest,
                            'address': address, 'offset': env['offset'],
                            'transactions': len(raw_txs), 'collected_utc': env['collected_utc']})
            for raw_tx in raw_txs:
                tx = normalize(raw_tx)
                # Cada transação deve envolver o endereço consultado.
                if address not in addresses(tx, 'inputs') + addresses(tx, 'outputs'):
                    raise ValueError(f'Histórico contém transação alheia ao endereço {address}')
                txs.append(tx)
                provenance.append({'txid': tx['txid'], 'source': page.relative_to(root).as_posix(),
                                   'address': address, 'offset': env['offset']})
    unique = deduplicate(txs)
    mapping, evidence = cluster(unique, mixers, seeds)
    sizes = Counter(mapping.values())
    seed_sizes = Counter(mapping[a] for a in seeds)
    before_nodes = {a: {'label': a, 'size': 1, 'seeds': int(a in seeds)} for a in mapping}
    after_nodes = {cid: {'label': cid, 'size': size, 'seeds': seed_sizes[cid]}
                   for cid, size in sizes.items()}
    fields = ['source', 'target', 'txid', 'time', 'input_address', 'output_address']
    write_csv(out/'address_to_cluster.csv', ['address', 'cluster', 'cluster_size', 'seed'],
              ({'address': a, 'cluster': c, 'cluster_size': sizes[c], 'seed': int(a in seeds)}
               for a, c in sorted(mapping.items())))
    write_csv(out/'nodes_before.csv', ['id', 'label', 'size', 'seeds'],
              ({'id': a, **d} for a, d in sorted(before_nodes.items())))
    write_csv(out/'nodes_after.csv', ['id', 'label', 'size', 'seeds'],
              ({'id': a, **d} for a, d in sorted(after_nodes.items())))
    write_csv(out/'edges_before.csv', fields, relations(unique))
    write_csv(out/'edges_after.csv', fields, relations(unique, mapping))
    write_csv(out/'h1_evidence.csv', ['txid', 'time', 'new_unions', 'input_addresses'],
              ({**e, 'input_addresses': json.dumps(e['input_addresses'])} for e in evidence))
    write_csv(out/'provenance.csv', ['txid', 'source', 'address', 'offset'], provenance)
    write_csv(out/'collection_status.csv', ['address', 'status', 'pages', 'unique_transactions', 'error'],
              ({k: s.get(k) for k in ['address', 'status', 'pages', 'unique_transactions', 'error']}
               for s in states))
    graphml(out/'before_addresses.graphml', before_nodes, unique, mixers)
    graphml(out/'after_h1.graphml', after_nodes, unique, mixers, mapping)
    relation_count = sum(1 for _ in relations(unique))
    loop_count = sum(e['source'] == e['target'] for e in relations(unique, mapping))
    excluded = sorted(t['txid'] for t in unique if t['txid'] in mixers)
    summary = {
        'created_utc': utc(), 'provider': provider, 'archive_sha256': manifest['archive_sha256'],
        'selection': manifest['selection'], 'total_supplied_transactions': manifest['total_transactions'],
        'total_supplied_input_addresses': manifest['total_unique_input_addresses'],
        'selected_transactions': len(manifest['selected']),
        'selected_input_occurrences': manifest['selected_input_occurrences'],
        'coverage': {'requested': len(seeds), 'complete': sum(s['status'] == 'complete' for s in states),
                     'errors': sum(s['status'] == 'error' for s in states),
                     'not_attempted': sum(s['status'] == 'not_attempted' for s in states),
                     'pages': len(sources),
                     'collection_min_utc': min(collected_times, default=None),
                     'collection_max_utc': max(collected_times, default=None)},
        'transactions': {'occurrences_including_selected': len(txs), 'unique': len(unique),
                         'history_unique': len({p['txid'] for p in provenance if p['address']}),
                         'coinbase': sum(t['coinbase'] for t in unique),
                         'missing_input_addresses': sum(t['missing_inputs'] for t in unique),
                         'missing_output_addresses': sum(t['missing_outputs'] for t in unique)},
        'h1': {'excluded_known_mixers': len(excluded), 'excluded_hashes': excluded,
               'evidence_transactions': len(evidence), 'successful_unions': sum(e['new_unions'] for e in evidence),
               'seed_clusters': len(seed_sizes), 'nontrivial_clusters': sum(s > 1 for s in sizes.values()),
               'largest_cluster_size': max(sizes.values(), default=0)},
        'graph': {'addresses': len(mapping), 'clusters': len(sizes),
                  'relations': relation_count, 'cluster_loops': loop_count},
        'selected_hashes': [t['txid'] for t in manifest['selected']],
        'largest_clusters': [{'cluster': cid, 'size': size, 'seed_count': seed_sizes[cid]}
                             for cid, size in sorted(sizes.items(), key=lambda x: (-x[1], x[0]))[:10]],
        'limitations': ['H1 é heurística, não identificação de pessoas.',
                       'Lista fornecida não garante exclusão de outros CoinJoins.',
                       'Relações entrada-saída não revelam o pareamento econômico.',
                       'Recorte cronológico não é amostra representativa.',
                       'Históricos consultados hoje; clusters não têm interpretação temporal anterior ao mixer.']}
    if len(mapping) - len(sizes) != summary['h1']['successful_unions']:
        raise AssertionError('Invariante de contração H1 violada')
    save_json(out/'summary.json', summary)
    save_json(out/'transactions.json', unique)
    save_json(out/'source_pages.json', sources)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'run'])
    parser.add_argument('--archive', type=Path, default=ROOT.parent/'wasabiTxs.tgz')
    parser.add_argument('--count', type=int, default=10)
    parser.add_argument('--part', type=int, default=0)
    parser.add_argument('--parts', type=int, default=1)
    parser.add_argument('--provider', choices=['rawaddr', 'gateway'], default='rawaddr')
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare(args)
    else:
        print(json.dumps(run(provider=args.provider), ensure_ascii=False, indent=2))
