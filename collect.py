"""Históricos Blockchain.com: paginação, cache atômico e retomada."""
import argparse
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import os
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen

from analyze import ROOT, normalize, save_json, utc


def page_transactions(data):
    if not isinstance(data, dict):
        raise ValueError('Resposta não é objeto JSON')
    txs = data.get('txs', data.get('transactions'))
    if not isinstance(txs, list):
        raise ValueError('Resposta sem lista de transações')
    for tx in txs:
        normalize(tx)
    return txs


def collect_address(address, cache, fetch, page_size=50):
    folder = Path(cache)/address
    folder.mkdir(parents=True, exist_ok=True)
    state = {'address': address, 'status': 'running', 'updated_utc': utc(),
             'pages': 0, 'unique_transactions': 0, 'expected_total': None,
             'error': None}
    seen = set()
    fingerprints = set()
    offset = 0
    try:
        # Limit prevents a changing/broken provider from generating an endless crawl.
        for _ in range(10000):
            path = folder/f'page_{offset:08d}.json'
            cached = path.exists()
            if cached:
                envelope = json.loads(path.read_text(encoding='utf-8'))
                if envelope['address'] != address or envelope['limit'] != page_size:
                    raise ValueError('Cache incompatível com endereço/tamanho de página')
                data = envelope['response']
            else:
                data = fetch(address, offset, page_size)
                envelope = {'address': address, 'offset': offset, 'limit': page_size,
                            'collected_utc': utc(), 'response': data}
            txs = page_transactions(data)
            if len(txs) > page_size:
                raise ValueError('Página excede o limite solicitado')
            if 'address' in data and data['address'] != address:
                raise ValueError('API devolveu outro endereço')
            ids = [tx.get('hash', tx.get('txId')) for tx in txs]
            fingerprint = tuple(ids)
            if ids and (fingerprint in fingerprints or seen.intersection(ids)):
                raise ValueError('Página repetida/sobreposta: histórico mudou ou offset ignorado')
            if len(set(ids)) != len(ids):
                raise ValueError('Transação duplicada dentro da página')
            total = data.get('n_tx')
            if total is not None:
                if type(total) is not int or total < 0:
                    raise ValueError('total de transações inválido')
                if state['expected_total'] is not None and total != state['expected_total']:
                    raise ValueError('total mudou entre páginas; refazer snapshot')
                state['expected_total'] = total
            if not cached:
                save_json(path, envelope)
            fingerprints.add(fingerprint)
            seen.update(ids)
            state.update(pages=state['pages'] + 1, unique_transactions=len(seen))
            if len(txs) < page_size:
                if state['expected_total'] is not None and len(seen) != state['expected_total']:
                    raise ValueError('Página final incompatível com total informado')
                state['status'] = 'complete'
                break
            offset += page_size
            save_json(folder/'status.json', state)
        else:
            raise ValueError('Limite de segurança de paginação atingido')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        state['status'] = 'error'
        state['error'] = str(exc)
    state['updated_utc'] = utc()
    save_json(folder/'status.json', state)
    return state


class Blockchain:
    def __init__(self, provider='rawaddr', interval=10, retries=3, timeout=30):
        self.provider = provider
        self.interval = interval
        self.retries = retries
        self.timeout = timeout
        self.last_request = 0
        self.log = ROOT/'data/request_log.jsonl'

    def __call__(self, address, offset, limit):
        api_key = os.environ.get('BLOCKCHAIN_API_KEY')
        headers = {'User-Agent': 'ESP-SEC-H1-academic/1.0', 'Accept': 'application/json'}
        if self.provider == 'gateway':
            url = 'https://api.blockchain.info/explorer-gateway-kt/btc/address/transactions'
            headers['Content-Type'] = 'application/json'
            if api_key:
                headers['X-Explorer-Auth-Key'] = api_key
            payload = json.dumps({'address': address, 'offset': offset, 'limit': limit}).encode()
        else:
            params = {'offset': offset, 'limit': limit}
            if api_key:
                params['api_code'] = api_key
            url = f'https://blockchain.info/rawaddr/{quote(address)}?' + urlencode(params)
            payload = None
        for attempt in range(self.retries):
            time.sleep(max(0, self.interval - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            entry = {'time_utc': utc(), 'provider': self.provider, 'address': address,
                     'offset': offset, 'limit': limit, 'attempt': attempt + 1}
            wait = 10 * 2**attempt
            try:
                with urlopen(Request(url, data=payload, headers=headers), timeout=self.timeout) as response:
                    body = response.read()
                    entry.update(status=response.status,
                                 response_sha256=hashlib.sha256(body).hexdigest())
                data = json.loads(body)
                page_transactions(data)
                return data
            except HTTPError as exc:
                entry.update(status=exc.code, error=f'HTTP {exc.code}')
                retry_after = exc.headers.get('Retry-After')
                if retry_after:
                    try:
                        wait = max(wait, float(retry_after))
                    except ValueError:
                        wait = max(wait, (parsedate_to_datetime(retry_after) -
                                         datetime.now(timezone.utc)).total_seconds())
                if exc.code != 429 and exc.code < 500:
                    raise OSError(f'HTTP {exc.code}') from None
                if attempt == self.retries - 1:
                    raise OSError(f'HTTP {exc.code} após {self.retries} tentativas') from None
            except (OSError, ValueError) as exc:
                # Do not print exception URLs: they could contain an optional API key.
                entry['error'] = type(exc).__name__
                if attempt == self.retries - 1:
                    raise OSError(f'Falha de rede/JSON ({type(exc).__name__})') from None
            finally:
                self.log.parent.mkdir(parents=True, exist_ok=True)
                with self.log.open('a', encoding='utf-8') as f:
                    f.write(json.dumps(entry) + '\n')
            time.sleep(wait)
        raise OSError('Tentativas esgotadas')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', choices=['rawaddr', 'gateway'], default='rawaddr')
    parser.add_argument('--interval', type=float, default=10)
    parser.add_argument('--retries', type=int, default=3)
    parser.add_argument('--timeout', type=float, default=30)
    args = parser.parse_args()
    if args.interval < 0 or args.retries < 1 or args.timeout <= 0:
        parser.error('Parâmetros de rede inválidos')
    manifest = json.loads((ROOT/'data/manifest.json').read_text(encoding='utf-8'))
    fetch = Blockchain(args.provider, args.interval, args.retries, args.timeout)
    states, failures = [], 0
    for index, address in enumerate(manifest['seed_addresses'], 1):
        state = collect_address(address, ROOT/'data/cache'/args.provider, fetch)
        states.append(state)
        failures = failures + 1 if state['status'] == 'error' else 0
        save_json(ROOT/'data/collection.json', {'provider': args.provider,
                  'updated_utc': utc(), 'requested_addresses': len(manifest['seed_addresses']),
                  'states': states, 'interval_seconds': args.interval,
                  'retries': args.retries})
        print(f'{index}/{len(manifest["seed_addresses"])} {address}: '
              f'{state["status"]}, {state["unique_transactions"]} tx, '
              f'{state["pages"]} pages' + (f' - {state["error"]}' if state['error'] else ''), flush=True)
        if failures >= 5:
            print('Cinco endereços consecutivos com erro; interrompendo. Execute novamente para retomar.', flush=True)
            break


if __name__ == '__main__':
    main()
