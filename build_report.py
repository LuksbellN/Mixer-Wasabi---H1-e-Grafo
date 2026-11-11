"""Figuras e relatório acadêmico curto, gerados dos resultados auditáveis."""
from collections import Counter
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
from xml.sax.saxutils import escape

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import networkx as nx
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, Table, TableStyle

from analyze import ROOT, addresses, relations, save_json

INK, BLUE, TEAL, GRAY, ORANGE = '#202020', '#555555', '#333333', '#999999', '#666666'
REPO = 'https://github.com/LuksbellN/Mixer-Wasabi---H1-e-Grafo'
W, H = A4
M, CW = 43, W - 86


def n(value):
    return f'{value:,}'.replace(',', '.')


def date(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime('%d/%m/%Y')


def load():
    result = ROOT/'results'
    summary = json.loads((result/'summary.json').read_text(encoding='utf-8'))
    txs = json.loads((result/'transactions.json').read_text(encoding='utf-8'))
    manifest = json.loads((ROOT/'data/manifest.json').read_text(encoding='utf-8'))
    with (result/'address_to_cluster.csv').open(encoding='utf-8-sig') as f:
        mapping = {r['address']: r['cluster'] for r in csv.DictReader(f)}
    return summary, txs, manifest, mapping


def graphs(txs, mapping, seeds):
    before, after = nx.DiGraph(), nx.DiGraph()
    before.add_nodes_from(mapping)
    after.add_nodes_from(mapping.values())
    for edge in relations(txs):
        a, b = edge['source'], edge['target']
        before.add_edge(a, b)
        c, d = mapping[a], mapping[b]
        if after.has_edge(c, d):
            after[c][d]['weight'] += 1
        else:
            after.add_edge(c, d, weight=1)
    return before, after


def plot_overview(txs, mapping, seeds, folder):
    before, after = graphs(txs, mapping, seeds)
    # Same spatial basis: each cluster is positioned at its members' centroid.
    # Large samples use the scalable force implementation provided by NetworkX.
    pos = nx.spring_layout(before, seed=42, iterations=60)
    members = {}
    for a, c in mapping.items():
        members.setdefault(c, []).append(a)
    cpos = {c: sum((pos[a] for a in group))/len(group) for c, group in members.items()}
    seed_clusters = {mapping[a] for a in seeds}
    fig, axes = plt.subplots(1, 2, figsize=(10, 6.3))
    for ax, graph, positions, marked, title in [
        (axes[0], before, pos, seeds, 'Antes: endereços'),
        (axes[1], after, cpos, seed_clusters, 'Depois: clusters H1')]:
        nx.draw_networkx_edges(graph, positions, ax=ax, edge_color=GRAY, alpha=.12,
                               width=.35, arrows=True, arrowsize=3, node_size=7)
        nx.draw_networkx_nodes(graph, positions, ax=ax, node_size=8,
                               node_color=[TEAL if a in marked else '#bfbfbf' for a in graph])
        ax.set_title(f'{title}\n{n(len(graph))} vértices', fontsize=11)
        ax.set_axis_off()
    fig.legend(handles=[Line2D([0], [0], marker='o', color='w', markerfacecolor=TEAL,
                               label='Entrada do recorte / cluster que a contém', markersize=6),
                        Line2D([0], [0], marker='o', color='w', markerfacecolor='#bfbfbf',
                               label='Demais endereços / clusters observados', markersize=6)],
               loc='lower center', frameon=False, fontsize=8, ncol=1)
    fig.subplots_adjust(left=.01, right=.99, top=.91, bottom=.1, wspace=.08)
    fig.savefig(folder/'graphs_overview.png', dpi=190)
    plt.close(fig)


def plot_example(txs, mapping, seeds, mixers, folder):
    candidates = [t for t in txs if t['txid'] not in mixers
                  and 2 <= len(addresses(t, 'inputs')) <= 7
                  and 1 <= len(addresses(t, 'outputs')) <= 4]
    candidates.sort(key=lambda t: (-len(set(addresses(t, 'inputs')) & seeds),
                                   -len(set(addresses(t, 'outputs')) & seeds),
                                   len(addresses(t, 'inputs')), t['txid']))
    if not candidates:
        raise ValueError('Sem exemplo legível de H1 nas transações coletadas')
    tx = candidates[0]
    ins, outs = addresses(tx, 'inputs'), addresses(tx, 'outputs')
    all_a = sorted(set(ins + outs))
    labels = {a: f'A{i+1}' for i, a in enumerate(all_a)}
    cids = sorted({mapping[a] for a in all_a})
    clabels = {c: f'C{i+1}' for i, c in enumerate(cids)}
    cluster_sizes = Counter(mapping.values())
    before, after = graphs([tx], {a: mapping[a] for a in all_a}, seeds)
    # Two columns: inputs on the left, outputs on the right; shared address centered.
    both = set(ins) & set(outs)
    pos = {}
    for group, x in [(sorted(set(ins) - both), 0), (sorted(both), .5),
                     (sorted(set(outs) - both), 1)]:
        for i, a in enumerate(group):
            pos[a] = (x, (i + 1)/(len(group) + 1))
    cpos = nx.spring_layout(after, seed=5, iterations=70)
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.4))
    for ax, g, p, text, title in [(axes[0], before, pos, labels, 'Endereços'),
                                 (axes[1], after, cpos, clabels, 'Clusters H1')]:
        nx.draw_networkx_nodes(g, p, ax=ax, node_size=750, node_color='#f5f5f5',
                               edgecolors=TEAL, linewidths=1.2)
        nx.draw_networkx_labels(g, p, labels=text, ax=ax, font_size=10)
        nx.draw_networkx_edges(g, p, ax=ax, arrows=True, arrowsize=13, node_size=750,
                               edge_color=BLUE, width=1.2, connectionstyle='arc3,rad=0.08')
        if g is after:
            edge_labels = {(a, b): f'{d["weight"]} rel.' for a, b, d in g.edges(data=True)
                           if a != b and d['weight'] > 1}
            nx.draw_networkx_edge_labels(g, p, edge_labels=edge_labels, ax=ax, font_size=8)
        ax.set_title(title, fontsize=11)
        ax.margins(.28)
        ax.set_axis_off()
    fig.tight_layout()
    fig.savefig(folder/'h1_example.png', dpi=190)
    plt.close(fig)
    example = {'txid': tx['txid'], 'time': tx['time'], 'inputs': len(ins), 'outputs': len(outs),
               'before_vertices': len(all_a), 'after_vertices': len(cids),
               'relations': len(ins)*len(outs),
               'addresses': [{'label': labels[a], 'address': a, 'cluster_label': clabels[mapping[a]],
                              'cluster': mapping[a], 'seed': a in seeds} for a in all_a],
               'clusters': [{'label': clabels[c], 'id': c, 'size_in_full_graph': cluster_sizes[c]}
                            for c in cids]}
    save_json(folder.parent/'example.json', example)
    return example


class Report:
    def __init__(self, dest):
        fontdir = Path(matplotlib.get_data_path())/'fonts/ttf'
        for name, filename in [('Body', 'DejaVuSans.ttf'), ('Bold', 'DejaVuSans-Bold.ttf'),
                               ('Mono', 'DejaVuSansMono.ttf')]:
            pdfmetrics.registerFont(TTFont(name, str(fontdir/filename)))
        pdfmetrics.registerFontFamily('Body', normal='Body', bold='Bold',
                                      italic='Body', boldItalic='Bold')
        self.c = canvas.Canvas(str(dest), pagesize=A4)
        self.c.setTitle('Wasabi: clusterização H1 e grafos de pagamentos')
        self.c.setAuthor('Lucas Panonko Assis Belchior')
        self.page = 0

    def cover(self):
        # Mesmas posições, fontes e hierarquia da capa do trabalho CPFP.
        self.page = 1
        c = self.c

        def center(y, text, size=11, font='Body'):
            c.setFont(font, size)
            c.setFillColor(colors.HexColor(INK))
            c.drawCentredString(W/2, y, text)

        center(H-115, 'Tópicos Especiais de Segurança', 12, 'Bold')
        center(H-185, 'Lucas Panonko Assis Belchior')
        center(H-205, 'Matrícula: 12311BCC068', 10)
        center(H/2+15, 'Wasabi: clusterização H1', 24, 'Bold')
        center(H/2-15, 'Análise de endereços de entrada e grafos de pagamentos', 10)
        center(H/2-90, 'Repositório do projeto', 10, 'Bold')
        center(H/2-110, REPO, 8)
        c.linkURL(REPO, (M, H/2-115, W-M, H/2-95), relative=0)
        center(110, '11 de novembro de 2026', 10)

    def new(self, title):
        if self.page:
            self.c.showPage()
        self.page += 1
        c = self.c
        c.setStrokeColor(colors.HexColor(GRAY))
        c.setLineWidth(.5)
        c.line(M, H - 35, W - M, H - 35)
        c.setFont('Body', 8)
        c.setFillColor(colors.HexColor('#666666'))
        c.drawString(M, H - 27, 'TÓPICOS ESPECIAIS DE SEGURANÇA | WASABI E H1')
        c.drawString(M, 25, 'Lucas Panonko Assis Belchior | 12311BCC068 | 11/11/2026')
        c.drawRightString(W - M, 25, f'{self.page} / 5')
        self.y = H - 62
        self.p(title, 19, 'Bold', 25)
        self.y -= 6

    def p(self, text, size=9.6, font='Body', leading=None):
        para = Paragraph(text, ParagraphStyle('p', fontName=font, fontSize=size,
                          leading=leading or size*1.42, textColor=colors.HexColor(INK)))
        _, height = para.wrap(CW, H)
        if self.y - height < 45:
            raise ValueError(f'Página {self.page} ultrapassada: {text[:70]}')
        para.drawOn(self.c, M, self.y - height)
        self.y -= height + 9

    def table(self, rows, widths=None, size=9):
        style = ParagraphStyle('cell', fontName='Body', fontSize=size, leading=size*1.35)
        values = [[Paragraph(escape(str(c)), style) for c in row] for row in rows]
        table = Table(values, colWidths=widths or [CW*.67, CW*.33], hAlign='LEFT')
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#eeeeee')),
            ('LINEBELOW', (0, 0), (-1, 0), .5, colors.HexColor(TEAL)),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 7),
            ('RIGHTPADDING', (0, 0), (-1, -1), 7),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LINEBELOW', (0, 1), (-1, -1), .25, colors.HexColor('#dce1e3'))]))
        _, height = table.wrap(CW, H)
        if self.y - height < 45:
            raise ValueError(f'Tabela ultrapassa página {self.page}')
        table.drawOn(self.c, M, self.y - height)
        self.y -= height + 12

    def image(self, path, height):
        if self.y - height < 45:
            raise ValueError('Figura ultrapassa página')
        self.c.drawImage(str(path), M, self.y - height, width=CW, height=height,
                         preserveAspectRatio=True, anchor='c', mask='auto')
        self.y -= height + 10


def main():
    s, txs, manifest, mapping = load()
    coverage, stats, h1, g = s['coverage'], s['transactions'], s['h1'], s['graph']
    folder = ROOT/'results/figures'
    folder.mkdir(parents=True, exist_ok=True)
    seeds, mixers = set(manifest['seed_addresses']), set(manifest['mixers'])
    seed_groups = Counter(mapping[a] for a in seeds)
    grouped_seeds = sum(size for size in seed_groups.values() if size > 1)
    separate_seeds = sum(size == 1 for size in seed_groups.values())
    plot_overview(txs, mapping, seeds, folder)
    example = plot_example(txs, mapping, seeds, mixers, folder)
    dest = ROOT/'report/Wasabi_H1_Lucas_Belchior.pdf'
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = Report(dest)
    r.cover()
    r.new('Visão geral do trabalho')
    r.p('01 / OBJETIVO E METODOLOGIA', 9, 'Bold')
    r.p('Aplicar a heurística H1 aos históricos dos endereços de <b>entrada</b> das transações '
        'fornecidas, retirando os mixers das uniões. Em seguida, comparar dois grafos: '
        'um com endereços nos vértices e outro com os clusters encontrados pelo H1.')
    r.table([['Transações do recorte', 'Históricos completos', 'Transações distintas'],
             [n(s['selected_transactions']), f'{coverage["complete"]} / {coverage["requested"]}',
              n(stats['unique'])]], widths=[CW/3]*3, size=12)
    r.p('Dados e recorte', 12, 'Bold')
    r.p(f'O arquivo fornecido contém <b>{n(s["total_supplied_transactions"])} transações</b> '
        f'e {n(s["total_supplied_input_addresses"])} endereços de entrada distintos. '
        'Foram selecionadas as dez primeiras transações na ordem por horário e hash, '
        f'de {date(manifest["selected"][0]["time"])} a {date(manifest["selected"][-1]["time"])} (UTC): '
        f'{s["selected_input_occurrences"]} entradas e {coverage["requested"]} endereços distintos. '
        'Foi usado esse recorte para limitar o número de consultas, considerando a possibilidade '
        'de divisão do trabalho mencionada pelo professor. As demais transações não foram analisadas.')
    if coverage['complete'] != coverage['requested']:
        r.p(f'<b>Coleta parcial:</b> {coverage["errors"]} erros e '
            f'{coverage["not_attempted"]} endereços sem conclusão. Os resultados dependem dessa cobertura.')
    r.p('Coleta e conferência dos históricos', 12, 'Bold')
    r.p('O endpoint POST do professor respondeu HTTP 503 no teste inicial. A coleta foi feita '
        'por <font name="Mono">blockchain.info/rawaddr</font>, também do Blockchain.com. '
        'O código pede 50 transações por página, aumenta o offset e espera 10 segundos entre '
        'consultas. Os JSONs são salvos para não baixar novamente o que já foi obtido. '
        'O fim da coleta é conferido pelo tamanho da última página e pelo total informado pela API. '
        'Páginas repetidas ou contagens diferentes geram erro.')
    r.p('Regra H1 e transitividade', 12, 'Bold')
    r.p('H1 considera que os endereços usados como entradas de uma mesma transação '
        'são controlados pela mesma entidade [1]. Depois de remover cópias da mesma transação, '
        'identificadas pelo hash, o algoritmo segue estes passos: '
        '<br/>1. Excluir das uniões todos os <b>1.001 hashes de mixer</b> do arquivo original.'
        '<br/>2. Unir os endereços de entrada de cada transação restante usando '
        '<i>union-find</i>, uma estrutura de conjuntos disjuntos.'
        '<br/>3. Aplicar a transitividade: se A aparece com B e B aparece com C, '
        'os três ficam no mesmo cluster. Endereços sem união permanecem separados. '
        'Não foi usada heurística de troco.')
    r.p('Resultado da clusterização', 12, 'Bold')
    r.p(f'Foram salvas {coverage["pages"]} páginas. Nos históricos, '
        f'{h1["excluded_known_mixers"]} mixers conhecidos foram excluídos das uniões; '
        f'{h1["evidence_transactions"]} transações elegíveis com múltiplos endereços '
        f'geraram {h1["successful_unions"]} uniões novas. '
        f'Entre os {coverage["requested"]} endereços usados na coleta, foram encontrados '
        f'{h1["seed_clusters"]} clusters. A lista de mixers usada é a do arquivo do exercício; '
        'não foi criado um detector de CoinJoin.', 9.2)

    r.new('Grafos antes e depois do H1')
    r.p('02 / GRAFOS', 9, 'Bold')
    r.p('Mesmo conjunto de transações, duas representações', 12, 'Bold')
    r.p('No grafo original, cada vértice é um endereço. Para cada transação, cria-se uma '
        'aresta dirigida de cada endereço distinto de entrada para cada endereço distinto de '
        'saída. No grafo agrupado, cada endereço é substituído pelo seu cluster H1. '
        'As transações de mixer permanecem como relações no grafo; sua exclusão vale para as uniões H1.')
    r.image(folder/'graphs_overview.png', 290)
    r.p('Figura 1. Os dois grafos usam as mesmas transações. Arestas repetidas entre o '
        'mesmo par aparecem sobrepostas no desenho; os arquivos GraphML e CSV guardam '
        'cada relação e o hash da transação. A posição dos vértices serve apenas para organizar a figura.', 8.5)
    r.table([['Medida', 'Endereços', 'Clusters H1'],
             ['Vértices', n(g['addresses']), n(g['clusters'])],
             ['Relações dirigidas, com multiplicidade', n(g['relations']), n(g['relations'])],
             ['Laços após contração', '-', n(g['cluster_loops'])]],
            widths=[CW*.54, CW*.23, CW*.23], size=8.5)
    r.p('<b>Como ler as arestas:</b> uma ligação indica que os endereços participaram da '
        'mesma transação como entrada e saída. Ela não informa qual entrada financiou cada '
        'saída; por isso, não recebe um valor em BTC. “Antes/depois” compara os grafos por '
        'endereço e por cluster. Isso não permite identificar qual saída do mixer pertence a cada participante.', 9)

    r.new('Exemplo e análise dos resultados')
    r.p('03 / RESULTADOS', 9, 'Bold')
    r.p('Uma transação usada no H1', 12, 'Bold')
    r.p(f'Exemplo de {date(example["time"])} (UTC): hash completo abaixo. '
        f'Possui {example["inputs"]} endereços de entrada distintos e '
        f'{example["outputs"]} de saída. Ela não está na lista de mixers. '
        'Seus endereços de entrada são unidos pelo H1.')
    r.p(example['txid'][:32] + '<br/>' + example['txid'][32:], 8, 'Mono')
    r.image(folder/'h1_example.png', 220)
    r.p(f'Figura 2. A mesma transação em detalhe: {example["before_vertices"]} vértices por '
        f'endereço e {example["after_vertices"]} por cluster. As {example["relations"]} relações '
        'originais continuam no arquivo agrupado. A marca “rel.” indica multiplicidade, sem valor monetário.', 8.5)
    r.table([['Vértice', 'Endereço abreviado', 'Cluster']] +
            [[a['label'], a['address'][:12] + '...' + a['address'][-6:], a['cluster_label']]
             for a in example['addresses']], widths=[CW*.15, CW*.65, CW*.2], size=8)
    r.p(f'Dos {coverage["requested"]} endereços de entrada selecionados, '
        f'{grouped_seeds} foram agrupados com outro endereço da seleção; '
        f'os outros {separate_seeds} não foram unidos a outro endereço desse conjunto. '
        f'Assim, as entradas ficaram distribuídas em {h1["seed_clusters"]} clusters. '
        f'A redução de {g["addresses"]} para {g["clusters"]} vértices da página anterior '
        'inclui também outros endereços encontrados nos históricos. Ela não deve ser '
        'confundida com a redução entre os endereços selecionados.', 9)
    r.p('Os endereços completos da tabela estão em <font name="Mono">results/example.json</font>. '
        'As transações usadas nas uniões estão em <font name="Mono">h1_evidence.csv</font>; '
        'os JSONs baixados permitem conferir suas entradas.', 8.5)

    r.new('Limitações e reprodução')
    r.p('04 / DISCUSSÃO E REPRODUÇÃO', 9, 'Bold')
    r.p('Limitações', 12, 'Bold')
    for text in [
        'As dez transações foram escolhidas pela ordem de data, sem sorteio. Os resultados '
        'valem para esse recorte e não descrevem todo o uso do Wasabi.',
        'Os históricos foram consultados em 11/11/2026. Eles podem conter transações anteriores '
        'e posteriores aos mixers; os clusters não mostram apenas o que era conhecido antes da mistura.',
        'H1 é uma heurística, não uma identificação de pessoas. CoinJoin e PayJoin podem reunir '
        'entradas de participantes diferentes [2]. Como o filtro usa apenas a lista fornecida, '
        'outros casos desse tipo podem gerar uniões incorretas.',
        f'Entradas sem endereço: {stats["missing_input_addresses"]}; saídas sem endereço: '
        f'{stats["missing_output_addresses"]}. Foram usados os históricos retornados pelo '
        'Blockchain.com, sem conferência em um nó Bitcoin próprio.']:
        r.p(text, 9)
    r.p('Como reproduzir', 12, 'Bold')
    r.p('Python 3.12+; executar na pasta do trabalho. Os JSONs incluídos permitem '
        'refazer a análise sem novas consultas. Para refazer também a seleção, colocar o '
        '<font name="Mono">wasabiTxs.tgz</font> original da disciplina na pasta superior.', 9)
    for command in ['python -m pip install -r requirements.txt',
                    'python -m unittest -v', 'python analyze.py prepare --count 10',
                    'python collect.py', 'python analyze.py run', 'python build_report.py',
                    'python verify.py', 'python package.py']:
        r.p(escape(command), 8, 'Mono', 10)
    r.p('Arquivo original: SHA-256', 9, 'Bold')
    digest = s['archive_sha256']
    r.p(digest[:32] + '<br/>' + digest[32:], 7.8, 'Mono', 10)
    r.p('Referências', 12, 'Bold')
    r.p('[1] Meiklejohn et al. <i>A Fistful of Bitcoins: Characterizing Payments Among Men '
        'with No Names</i>. IMC, 2013. DOI: 10.1145/2504730.2504747. '
        '<link href="https://cseweb.ucsd.edu/~smeiklejohn/files/imc13.pdf" color="#333333">Artigo original</link>.', 8)
    r.p('[2] Dorier. <i>BIP 78: A Simple Payjoin Proposal</i>, seção Motivation. '
        '<link href="https://bitcoin.org/bip/78/" color="#333333">bitcoin.org/bip/78</link>. '
        '[3] Enunciado, orientações e arquivo fornecidos pelo professor; históricos públicos '
        'obtidos em blockchain.info/rawaddr. Consultas em 11/11/2026.', 8)
    r.p('Código, dados coletados e resultados acompanham o ZIP de reprodução; sua cópia '
        'também está anexada ao PDF final. O arquivo original da disciplina não é duplicado.', 8)
    r.c.save()
    print(dest)


if __name__ == '__main__':
    main()
