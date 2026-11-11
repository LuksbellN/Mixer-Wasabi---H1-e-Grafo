# Wasabi — clusterização H1

Trabalho de **Tópicos Especiais de Segurança**.

**Lucas Panonko Assis Belchior — 12311BCC068**

[Repositório do projeto](https://github.com/LuksbellN/Mixer-Wasabi---H1-e-Grafo)

## Objetivo

Baixar os históricos dos endereços de entrada das transações fornecidas, aplicar H1 sem usar os mixers nas uniões e gerar dois grafos: um por endereço e outro por cluster.

## Dados utilizados

O arquivo `../wasabiTxs.tgz` tem 1.001 transações e 73.454 endereços de entrada distintos. Para limitar a coleta, foram usadas as dez primeiras transações na ordem por data e hash, de 08/11/2017 a 15/09/2018 (UTC). Elas contêm 134 entradas e **129 endereços distintos**.

O professor permitiu dividir o conjunto entre grupos. Este trabalho apresenta somente o recorte de dez transações. Não é uma amostra aleatória nem uma análise de todo o arquivo.

A coleta foi feita em 11/11/2026, entre 13h42 e 14h03, horário de São Paulo. O endpoint POST do exemplo respondeu HTTP 503 no teste inicial; foi usada a alternativa pública `blockchain.info/rawaddr`, também do Blockchain.com. Todos os 129 históricos foram obtidos.

## Resultado

| Medida | Quantidade |
|---|---:|
| Históricos completos | 129 / 129 |
| Transações distintas nos históricos | 74 |
| Mixers encontrados e excluídos das uniões H1 | 10 |
| Transações com múltiplos endereços usadas no H1 | 37 |
| Uniões novas | 263 |
| Endereços em todo o grafo | 927 |
| Clusters em todo o grafo | 664 |
| Relações em cada grafo | 7.349 |
| Relações que viraram laços após H1 | 39 |
| Clusters que contêm os 129 endereços selecionados | 128 |

**Entre os 129 endereços selecionados, apenas dois foram unidos entre si.** Os outros 127 não foram unidos a outro endereço dessa seleção. O par é:

```text
14UT6Sc7k8J2CruRAEDjndvSiK1AcGvgXq
1A21n6ytujSVoTARhkREqYoXS9tKFPbyPf
```

A transação `b91f92637361407588596f6f158b684e14554942e03b1a5339283c0a6698af60`, mostrada no PDF, contém ambos como entradas. A redução global de 927 para 664 inclui também outros endereços encontrados nos históricos.

## Como funciona

1. `analyze.py prepare` lê o TAR e salva as transações selecionadas, seus endereços de entrada e a lista completa dos 1.001 hashes de mixer.
2. `collect.py` pede o histórico de cada endereço, com 50 transações por página e pausa de 10 segundos entre consultas. Salva os JSONs e confere a paginação. Se for interrompido, aproveita as páginas já baixadas.
3. `analyze.py run` remove cópias da mesma transação pelo hash e aplica H1. Os endereços usados juntos como entradas são unidos com union-find. A união é transitiva: A com B e B com C formam um cluster A, B, C. **Nenhum dos 1.001 hashes fornecidos é usado nessas uniões.** Não foi aplicada regra de troco.
4. `build_report.py` desenha os grafos com NetworkX/Matplotlib e monta o PDF com ReportLab.

Para os grafos, cada transação liga cada endereço distinto de entrada a cada endereço distinto de saída. Três entradas e duas saídas, por exemplo, geram seis relações. Isso indica participação na mesma transação; não mostra qual entrada financiou qual saída. Por esse motivo, as arestas não recebem valor em BTC.

No segundo grafo, cada endereço é substituído pelo seu cluster H1. Relações repetidas e laços são mantidos nos arquivos. Nos desenhos, arestas sobrepostas aparecem juntas para facilitar a leitura. Os mixers aparecem como relações nos grafos, mas não geram uniões H1.

## Como executar

Requer Python 3.12 ou superior. Na pasta do trabalho:

```powershell
python -m pip install -r requirements.txt
python -m unittest -v
python analyze.py run
python build_report.py
python verify.py
python package.py
```

Esses comandos usam os JSONs já incluídos. `verify.py` também precisa de `../wasabiTxs.tgz` para conferir o arquivo original. `package.py` atualiza o ZIP e o anexa ao PDF.

Para refazer a seleção e a coleta, antes de `analyze.py run`:

```powershell
python analyze.py prepare --archive ../wasabiTxs.tgz --count 10
python collect.py
```

O coletor salva os arquivos em `data/cache/`. A mesma chamada retoma uma coleta interrompida. Para outra seleção, trabalhar em uma cópia separada da pasta, preservando esta entrega. Se um histórico mudar durante a paginação, o programa registra erro; é necessário refazer a coleta daquele endereço.

A opção `--provider gateway` permite usar o endpoint POST do professor, caso esteja acessível. Nesse caso, usar também `python analyze.py run --provider gateway`. Uma chave opcional pode ser informada pela variável `BLOCKCHAIN_API_KEY`. Os caches de cada provedor são separados.

## Arquivos

- `report/Wasabi_H1_Lucas_Belchior.pdf`: capa e quatro páginas de relatório.
- `Wasabi_H1_Lucas_Belchior_codigo_dados.zip`: código, dados coletados e resultados; também anexado ao PDF.
- `data/manifest.json`: seleção, endereços e lista de mixers excluídos do H1.
- `data/cache/`: páginas baixadas e estado de coleta de cada endereço.
- `results/address_to_cluster.csv`: mapa dos endereços para os clusters.
- `results/h1_evidence.csv`: transações usadas nas uniões.
- `results/provenance.csv`: endereço e página de origem de cada transação.
- `results/before_addresses.graphml` e `after_h1.graphml`: grafos completos. Os CSVs `nodes_*` e `edges_*` contêm os mesmos vértices e relações.
- `results/summary.json` e `verification.json`: contagens e resultado das conferências.
- `results/example.json`: endereços completos e siglas do exemplo no PDF.

O cálculo fica em `analyze.py` e a coleta em `collect.py`. `verify.py` é uma conferência adicional: recalcula os clusters usando componentes conexos do NetworkX e compara os resultados com os CSVs. `package.py` serve apenas para preparar a entrega. Os testes usam exemplos pequenos, separados dos dados da atividade.

## Limitações

H1 é uma hipótese de controle comum, não uma identificação de pessoas. Outros CoinJoins ou PayJoins fora da lista fornecida podem gerar uniões incorretas. Os históricos foram os retornados pelo Blockchain.com, sem conferência em um nó próprio.

Os históricos consultados em 2026 podem incluir transações anteriores e posteriores aos mixers. A comparação “antes/depois” mostra endereços versus clusters; não reconstrói o conhecimento disponível antes de cada mistura nem descobre qual saída pertence a cada participante.

## Referências e integridade

- Enunciado e arquivos fornecidos pelo professor.
- Meiklejohn et al. [A Fistful of Bitcoins](https://cseweb.ucsd.edu/~smeiklejohn/files/imc13.pdf), IMC 2013. DOI: 10.1145/2504730.2504747.
- Dorier. [BIP 78: A Simple Payjoin Proposal](https://bitcoin.org/bip/78/), seção Motivation.

SHA-256 do arquivo original `wasabiTxs.tgz`:

```text
5e5d695e8d15ad4a8edccfbf9ed6373d484f5ed6ceb9e0110ac30d284695b422
```

O arquivo original não é duplicado no ZIP. As versões utilizadas estão em `data/environment.json`. Alguns leitores de navegador não mostram anexos PDF; nesse caso, usar o ZIP entregue separadamente.
