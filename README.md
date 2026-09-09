# Tradutor local de artigos científicos

Traduz artigos em PDF do inglês para o português brasileiro no seu próprio
computador. O texto é traduzido por um modelo local, e a diagramação original —
colunas, figuras, fórmulas e tabelas — é reconstruída no PDF de saída.

Nada é enviado para serviços de tradução na internet. Depois da preparação
inicial, o sistema funciona sem conexão.

Cada tradução gera dois arquivos: o **PDF em português** e um **PDF bilíngue**,
com as páginas do original e da tradução alternadas para conferência.

## O que é preciso

- Docker Desktop com suporte a GPU NVIDIA.
- Cerca de 8 GB livres em disco: 1,9 GB do modelo, o restante para a imagem e os
  recursos de leitura de PDF.
- Uma GPU com 8 GB de memória atende a configuração padrão. A medição feita
  neste projeto está em [docs/arquitetura-e-validacao.md](docs/arquitetura-e-validacao.md).

## Instalação

Todos os comandos são executados na pasta do projeto.

**1. Subir o serviço do modelo.**

```powershell
docker compose up -d modelo
```

**2. Construir a aplicação.**

```powershell
docker compose build app
```

**3. Preparar modelo e recursos.** Esta é a única etapa que usa a internet. Ela
baixa o modelo oficial (1,9 GB), confere o SHA-256 antes de importar, registra o
modelo no Ollama e baixa as fontes e o modelo de diagramação usados na leitura
dos PDFs. A execução leva alguns minutos e pode ser repetida sem prejuízo: o que
já está pronto não é baixado de novo.

```powershell
docker compose run --rm app python -m tradutor preparar
```

**4. Conferir.**

```powershell
docker compose run --rm app python -m tradutor diagnostico
```

A resposta traz o nome do modelo, o servidor local e os parâmetros registrados.

## Uso

### Pela interface web

```powershell
docker compose up -d app
```

Abra <http://127.0.0.1:8000>. A página recebe o PDF, mostra o andamento e
oferece os dois arquivos para download. O endereço aceita conexões apenas do
seu computador.

Para acompanhar os registros da aplicação:

```powershell
docker compose logs -f app
```

### Pelo terminal

Coloque o PDF na pasta `entrada/`, que aparece como `/entrada` dentro do
contêiner. Os resultados vão para `resultados/`, visível como `/resultados`.

```powershell
docker compose run --rm app python -m tradutor traduzir /entrada/artigo.pdf --saida /resultados
```

O andamento é escrito na saída de erro e o resultado final em JSON, com os
caminhos dos dois PDFs, a quantidade de páginas, o tempo gasto e os avisos do
motor. Cada tradução cria uma pasta própria dentro de `resultados/`, junto de um
`relatorio.json` com os mesmos dados.

Para traduzir um trecho solto, sem PDF — útil para avaliar o modelo:

```powershell
docker compose run --rm app python -m tradutor texto "The result was not significant (p = 0.12)."
```

Acrescente `--json` para ver também o tempo e a contagem de tokens.

### Sem internet

Depois da preparação, a tradução funciona sem conexão. Para comprovar isso, suba
os serviços em uma rede interna, que permite a conversa entre a aplicação e o
modelo, mas bloqueia a saída para a internet:

```powershell
docker compose -f compose.yaml -f compose.offline.yaml up -d
```

## Limites

- **Atende PDFs digitais**, com texto selecionável. Páginas digitalizadas são
  recusadas com uma mensagem clara, e texto dentro de imagens permanece em
  inglês, com aviso no relatório.
- **A preservação visual é aproximada.** O português ocupa mais espaço que o
  inglês, e o motor reflui o texto para caber. Tabelas densas e blocos de
  autoria merecem conferência.
- **Uma tradução por vez.** Um bloqueio em arquivo impede que duas execuções
  disputem a GPU.
- **Até 50 MB e 200 páginas** por arquivo.
- **É tradução automática.** Confira os termos, os números e as fórmulas no PDF
  bilíngue antes de citar qualquer trecho.

## Desenvolvimento

Os testes usam dependências simuladas e não precisam do modelo carregado:

```powershell
docker compose run --rm app python -m pytest
docker compose run --rm app ruff check .
```

Os testes verificam a leitura e a validação dos PDFs, a conversa com o modelo, o
fluxo de tradução, a coleta de avisos do motor e a interface web. Eles não
substituem a avaliação do modelo real nem a inspeção visual dos PDFs gerados,
descritas em [docs/arquitetura-e-validacao.md](docs/arquitetura-e-validacao.md).

## Organização

| Arquivo | Responsabilidade |
|---|---|
| `tradutor/config.py` | Configuração e recusa de qualquer destino que não seja local |
| `tradutor/pdf.py` | Inspeção do original e verificação estrutural da saída |
| `tradutor/modelo.py` | Conversa com o Ollama e validação das respostas |
| `tradutor/motor_pdf.py` | Ajuste do PDFMathTranslate e tradução dos nomes das etapas |
| `tradutor/servico.py` | Fluxo de tradução, avisos do motor e publicação dos resultados |
| `tradutor/tarefas.py` | Estado das tarefas da interface web |
| `tradutor/web.py` | Aplicação web e downloads |
| `tradutor/cli.py` | Comandos de terminal |
| `tradutor/preparar.py` | Download verificado do modelo e dos recursos de PDF |

O modelo traduz o texto; o motor de PDF identifica onde cada trecho fica e
reconstrói o documento; esta aplicação coordena as etapas e apresenta o
resultado.
