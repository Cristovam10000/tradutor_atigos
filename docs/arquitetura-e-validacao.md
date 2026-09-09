# Arquitetura e validação

Este documento registra como o sistema funciona, por que cada decisão foi
tomada, o que foi medido e o que ainda não foi comprovado. Ele acompanha apenas
o que está de fato implementado.

## 1. Fundamentos

A tradução de um artigo com diagramação preservada envolve três
responsabilidades distintas, e mantê-las separadas é o que torna o sistema
compreensível:

| Responsabilidade | Quem faz | O que entrega |
|---|---|---|
| Traduzir o texto | Modelo Hy-MT2-1.8B, executado pelo Ollama | Trechos em português |
| Saber onde o texto fica | PDFMathTranslate-next com BabelDOC | Posição de cada parágrafo e reconstrução das páginas |
| Coordenar e apresentar | Esta aplicação | Validação, andamento, verificação, publicação e avisos |

O modelo não sabe o que é uma página. O motor de PDF não sabe português. A
aplicação não traduz nem desenha: ela decide o que pode entrar, acompanha o
processamento, confere o que saiu e só então publica o resultado.

## 2. Decisões

### 2.1 Modelo

**Hy-MT2-1.8B em quantização Q8_0**, do repositório oficial
[tencent/Hy-MT2-1.8B-GGUF](https://huggingface.co/tencent/Hy-MT2-1.8B-GGUF),
licença Apache 2.0. É um modelo especializado em tradução, com suporte a
português, e o arquivo de 1,91 GB cabe com folga nos 8 GB da placa.

Q8_0 preserva mais precisão que Q4_K_M ao custo de memória. Como a placa é usada
separadamente de outros trabalhos, a medição confirmou que a escolha mais
precisa cabe: ver [§5](#5-resultados-medidos).

**A importação é verificada.** `preparar.py` fixa a revisão do repositório, o
tamanho e o SHA-256 do arquivo, e confere os dois antes de registrar o modelo no
Ollama. Um arquivo que não confira é recusado em vez de importado. O download é
retomável: uma interrupção não obriga a recomeçar do zero.

**O template foi convertido do `chat_template.jinja` oficial** para o formato do
Ollama, incluindo os marcadores de parada do modelo. Sem isso, o modelo não
encerra a resposta no ponto certo.

### 2.2 Execução do modelo

O Ollama roda em um serviço próprio, com uma tradução por vez
(`OLLAMA_NUM_PARALLEL=1`), um modelo carregado por vez
(`OLLAMA_MAX_LOADED_MODELS=1`) e contexto de 8.192 tokens. A configuração da
aplicação **recusa qualquer destino que não seja local**: `config.py` valida o
endereço, exige HTTP sem credenciais e rejeita nomes públicos. Um erro de
configuração não consegue transformar este projeto em cliente de um serviço
pago.

### 2.3 Motor de PDF

**PDFMathTranslate-next 2.9.0 com BabelDOC 0.6.2**, pela API recomendada
`do_translate_async_stream`, que entrega eventos de progresso, conclusão e erro.
A biblioteca não é modificada; apenas configurada.

O motor de tradução escolhido é o **`CLITranslator`**, que executa um comando
externo e passa o texto pela entrada padrão. O comando é nosso:
`python -m tradutor.traduzir_trecho`, que conversa com o Ollama local.

Essa escolha não é de gosto. Aos motores que falam com modelos de instrução, a
biblioteca envia um bloco de regras de formatação junto do texto; um modelo
especializado em traduzir traduz essas regras, e elas foram parar dentro do PDF
no lugar das legendas dos gráficos. Com este motor, esse bloco nunca é enviado:
ver [§5.3](#53-o-caminho-de-instruções-do-motor-não-serve-a-este-modelo).

Outros três ajustes merecem explicação:

- **`use_alternating_pages_dual=True`** produz o PDF bilíngue com páginas
  alternadas, que é o formato útil para conferir a tradução.
- **`watermark_output_mode="no_watermark"`** evita marca d'água em um documento
  de uso pessoal.
- **`disable_rich_text_translate=True`** evita pedir marcação de estilo dentro
  do parágrafo, que o modelo não reproduz.

### 2.4 O original é intocável

O motor recebe uma **cópia** do arquivo, dentro de um diretório temporário. Ao
final, o SHA-256 do original é recalculado e comparado com o inicial: se não
bater, a tradução falha em vez de ser publicada.

### 2.5 A existência de um arquivo não é sucesso

Este é o princípio central da verificação. O motor pode gravar arquivos e ainda
assim ter falhado. Antes de publicar, a aplicação exige, em ordem:

1. um evento `finish` explícito do motor — sem ele, é erro;
2. os dois caminhos de PDF no resultado;
3. `verificar_saida` em cada um: o arquivo abre, não está protegido, tem a
   quantidade certa de páginas (o bilíngue tem o dobro) e contém texto legível;
4. o SHA-256 do original inalterado.

Só depois disso os arquivos são gravados em um diretório temporário no mesmo
volume e **renomeados** para o destino final. Uma interrupção no meio do
processo não deixa uma pasta de resultado pela metade.

### 2.6 Uma tradução por vez

Um bloqueio em arquivo (`FileLock`) serializa as traduções entre processos, e o
gerenciador de tarefas recusa uma segunda tarefa na interface web. Duas
traduções simultâneas disputariam a mesma GPU e as duas ficariam mais lentas.

### 2.7 Os avisos do motor precisam chegar ao usuário

O motor executa em **outro processo**, criado a partir deste. Um manipulador de
log guardando mensagens em memória é copiado para o processo filho, e as
mensagens ficam na cópia — a lista do processo original chega vazia. Por isso
`ColetorAvisos` grava em arquivo, que é o ponto de encontro dos dois processos.

Esse detalhe não é teórico: ele foi encontrado em execução real e está descrito
em [§5.4](#54-os-avisos-do-motor-nao-chegavam-ao-relatorio).

## 3. Fluxo

```text
PDF de origem
  │
  ├─ inspecionar_pdf ......... extensão, tamanho, assinatura, senha, permissão
  │                            de cópia, número de páginas, texto selecionável
  ├─ verificar modelo ........ o Ollama responde e conhece o modelo
  │
  ├─ cópia em pasta temporária ......... o original não é tocado
  │
  ├─ motor de PDF (eventos) ............ leitura → diagramação → tradução
  │     progresso limitado a 95%         → tipografia → gravação
  │
  ├─ verificar_saida × 2 ............... traduzido e bilíngue
  ├─ SHA-256 do original ............... continua igual?
  │
  └─ publicação por renomeação ......... traduzido.pdf, bilingue.pdf,
                                         relatorio.json
```

O progresso do motor é limitado a 95% de propósito: os 5% restantes pertencem à
verificação. O usuário não vê 100% antes de o resultado ter sido conferido.

## 4. Testes automatizados

63 testes, executados com dependências simuladas — não exigem GPU nem modelo
carregado.

| Arquivo | O que cobre |
|---|---|
| `test_config.py` | Recusa de destinos externos, com ou sem credenciais |
| `test_pdf.py` | PDF válido, arquivo falso com extensão `.pdf`, PDF truncado, protegido por senha, digitalizado, misto, limite de tamanho, contagem de páginas na saída |
| `test_modelo.py` | Limites enviados ao modelo, métricas, resposta vazia, resposta truncada por limite, tipo errado, servidor fora do ar, modelo ausente, trecho longo demais |
| `test_servico.py` | Publicação do par de PDFs, original preservado, falhas que não podem virar sucesso, bloqueio entre instâncias, cancelamento, tempo excedido, avisos do motor no resultado, configuração real do motor |
| `test_avisos.py` | Coleta de avisos, filtragem de ruído, resumo do motor traduzido, deduplicação, **aviso emitido em processo filho**, falha de escrita sem interromper a tradução |
| `test_web.py` | Envio, consulta, download, arquivo falso, download antes da hora, reinício marcando tarefa interrompida, travessia de caminho, concorrência, cancelamento, nome de arquivo malicioso |
| `test_traduzir_trecho.py` | Instrução e limites enviados, limpeza do invólucro de destino, respostas inválidas, trecho vazio, trecho longo demais, falha de rede encerrando com erro, argumentos de servidor e modelo, recusa de servidor externo |

Três desses testes merecem destaque porque protegem decisões, e não apenas
código:

- `test_arquivos_existentes_nao_bastam_para_sucesso` roda o motor simulado em
  três modos de falha e confirma que **nenhum PDF é publicado** em nenhum deles.
- `test_aviso_emitido_em_processo_filho_chega_ao_pai` reproduz exatamente a
  falha descrita em §5.4.
- `test_download_nao_pode_sair_da_pasta_da_tarefa` confirma que um caminho
  gravado no estado da tarefa não consegue servir um arquivo de fora.
- `test_motor_nao_usa_o_caminho_de_instrucoes_da_biblioteca` verifica a sonda em
  que a biblioteca se baseia, e que sustenta toda a decisão de §5.3.
- `test_falha_de_rede_encerra_com_erro` garante que uma falha do modelo não
  publique o texto original como se estivesse traduzido.

Estes testes **não** comprovam qualidade de tradução nem fidelidade visual. Isso
é o assunto da próxima seção.

## 5. Resultados medidos

Equipamento: Intel Core 7 240H, 16 GB de memória, NVIDIA GeForce RTX 5050 Laptop
com 8.151 MiB, Windows 11 com Docker Desktop. Modelo `artigos-hymt2:q8`,
contexto de 8.192 tokens.

### 5.1 Memória e velocidade

| Medida | Valor |
|---|---|
| Modelo em memória de vídeo | 2,6 GB, **100% na GPU** |
| Uso total da placa durante a tradução | 2.894 MiB de 8.151 MiB |
| Utilização da GPU gerando texto | 85% a 87% |
| Memória principal, pico do motor (3 páginas) | 3.669 MB |
| Primeira chamada, com carga do modelo | 40,0 s |
| Chamada seguinte, modelo já carregado | 1,74 s para 171 tokens (≈ 98 tokens/s) |

A expectativa do planejamento — caber nos 8 GB — **se confirmou com folga**: a
configuração Q8_0 com contexto de 8.192 usa pouco mais de um terço da placa.

### 5.2 Qualidade da tradução

Trecho técnico traduzido pelo comando `texto`, com negação, números e
terminologia:

> *We did not observe a statistically significant degradation when label
> smoothing was disabled (p = 0.12).*
>
> **Não observamos uma degradação estatisticamente significativa quando o
> suavização de rótulos foi desativado (p = 0,12).**

O que se confirmou: a negação é preservada, os números permanecem corretos,
`28.4 BLEU` e `p = 0.12` chegam íntegros e a terminologia técnica é adequada.

O que se observou de problemático:

- **Concordância de gênero falha às vezes.** "o suavização... desativado"
  deveria ser "a suavização... desativada". Aparece em trechos com termos
  técnicos traduzidos.
- **O separador decimal é convertido**: `0.12` vira `0,12`, `alpha = 0.001` vira
  `alpha = 0,001`. Está correto para o português corrido, mas é uma armadilha em
  hiperparâmetros e código, onde a vírgula muda o significado.
- **O tempo verbal muda**: "We propose" saiu como "Propusemos".

### 5.3 O caminho de instruções do motor não serve a este modelo

Este foi o achado que mais mudou o projeto.

O BabelDOC tem dois tradutores internos, e escolhe entre eles **sondando o motor**:

```python
if translate_engine and hasattr(translate_engine, "do_llm_translate"):
    translate_engine.do_llm_translate(None)
    self.support_llm_translate = True
except NotImplementedError:
    self.support_llm_translate = False
```

Quando a sonda passa, a biblioteca envia ao modelo um bloco de regras de
formatação junto do texto — *"## Rules 1. Keep the structure exactly unchanged:
do NOT add/remove/reorder any tags, placeholders, or tokens..."* — e espera a
resposta em JSON.

O Hy-MT2 é um modelo de tradução, não de instrução. Ele **traduziu as regras**
em vez de segui-las. O resultado medido em um artigo de 3 páginas com o motor
compatível com OpenAI:

```text
WARNING  Error Expecting value: line 1 column 1 (char 0) during translation. try fallback
INFO     Translation completed. Total: 56, Successful: 0, Fallback: 56
```

E, pior que o desperdício, o texto das regras foi parar dentro do PDF, no lugar
das legendas dos gráficos: ver [§5.6](#56-artigos-completos).

**A solução foi trocar o motor, não o modelo.** Dos 16 motores do
PDFMathTranslate, 7 não implementam `do_llm_translate` — entre eles o
`CLITranslator`, que executa um comando externo e passa o texto por stdin. Com
ele, `support_llm_translate` fica falso, a biblioteca usa o tradutor simples e o
bloco de regras **nunca é enviado**. Não é uma questão de probabilidade: o
`PROMPT_TEMPLATE` só é usado dentro de `generate_prompt_for_llm`, que só é
chamado sob aquele `if`.

O comando é [`tradutor/traduzir_trecho.py`](../tradutor/traduzir_trecho.py), que
recebe o trecho por stdin, conversa com o Ollama e devolve a tradução. Ele evita
importar httpx e pydantic de propósito: o motor executa um processo por trecho, e
essas dependências custam 0,33 s a cada chamada — mais de dois minutos em um
artigo de 500 trechos. A medição da partida do processo:

| O que se importa | Custo por execução |
|---|---:|
| Biblioteca padrão apenas | 196 ms |
| `tradutor.config` + `urllib` + `json` | 296 ms |
| `tradutor.config` + `tradutor.modelo` (httpx, pydantic) | 630 ms |
| `tradutor.cli` completo | 868 ms |

Servidor e modelo vão como argumentos no comando, e não pelo ambiente, para que
a configuração do processo principal seja a que vale. O processo filho monta um
`Config`, o que faz a recusa de servidores externos valer também ali.

**O que se perde:** glossário automático e os demais recursos do caminho de
instruções, que já estavam desligados; e um processo do sistema por trecho, cujo
custo está medido acima e é menor que o do caminho antigo.

### 5.4 Os avisos do motor não chegavam ao relatório

Na primeira execução real, o motor emitiu 18 avisos, todos visíveis no terminal,
e o `relatorio.json` saiu com a lista de avisos praticamente vazia. A causa: o
PDFMathTranslate executa a tradução em um **processo filho**, que herda os
manipuladores de log já instalados. O coletor guardava mensagens em uma lista em
memória; o filho preenchia a sua cópia, e a lista do processo original
permanecia vazia.

Corrigido gravando os avisos em arquivo, que vale para os dois processos. O
nível dos registradores do motor também passou a ser fixado explicitamente,
porque o resumo do motor chega como informação, e não como aviso — em um
servidor configurado em WARNING, ele seria descartado antes de ser lido.

### 5.5 Inspeção visual dos PDFs

As páginas geradas foram convertidas em imagens e comparadas com o original.

**O que se preservou bem:**

- **Duas colunas** e **uma coluna**, com a ordem de leitura correta.
- **Fórmulas em destaque, com a numeração**: as equações (1) e (2) do artigo de
  duas colunas chegaram intactas, inclusive `y = F(x, {Wi}) + x`.
- **Matemática no meio da frase**: `H(x)`, `h_{t-1}`, `W_s`, `3×3`.
- **Referências numéricas**: `[13]`, `[35, 2, 5]`.
- **Figuras e legendas**: os gráficos permaneceram no lugar, com a legenda
  traduzida.
- **Itálico de bloco**, como o resumo em destaque.

**O que exige conferência:**

- **Palavras quebradas na mudança de linha.** Onde o original quebrava uma
  palavra, a saída manteve a separação em pontos novos: "de f orma
  assintótica", "não li neares", "por l ayer", "alcançou u m erro de 3,57%". É o
  defeito visual mais frequente.
- **Blocos de autoria se comprimem.** Nomes, afiliações e endereços de e-mail se
  aglutinam, e um endereço chegou com fonte reduzida para caber.
- **A numeração de seção pode migrar para o fim do título**: "3 Model
  Architecture" saiu como "Arquitetura do Modelo 3".
- **Terminologia oscila** entre traduzir e manter em inglês: "layers" e
  "camadas" aparecem na mesma página.
- **Rótulos dentro de imagens** não são traduzidos, como esperado, porque são
  parte do desenho.

### 5.6 Artigos completos

Os dois artigos foram traduzidos por inteiro, do começo ao fim, com o modelo e o
motor reais.

| | Duas colunas (ResNet) | Uma coluna (Attention) |
|---|---:|---:|
| Páginas | 12 | 15 |
| Tempo total | **452 s (7 min 33 s)** | 591 s (9 min 51 s) |
| Tempo por página | 37,7 s | 39,4 s |
| Memória principal, pico | 3.866 MB | 4.839 MB |
| Blocos com instrução vazada | **0** | 0 |
| Parágrafos não exportados | **0** | 0 |

**Nenhuma página perdeu texto.** A razão entre a quantidade de caracteres da
tradução e a do original ficou entre 1,05 e 1,18 em todas as 12 páginas — o
português é mais longo que o inglês, e a razão acompanha isso de forma uniforme.

#### O defeito que motivou a troca de motor

A medição anterior, com o motor compatível com OpenAI, registrava na mesma
página 8 uma razão de 1,66. A causa estava visível ao ampliar a figura: a
legenda do gráfico da esquerda da Figura 6, que deveria conter quatro rótulos
curtos, havia sido substituída por 776 caracteres com as regras internas do
motor traduzidas:

```text
## Regras
1. Mantenha a estrutura exatamente inalterada: NÃO adicione/remova/reordene
   tags, placeholders ou tokens.
2. Mantenha todos os tags inalterados (por exemplo, <style>, <b>, </style>).
```

Eram 7 blocos assim, nas páginas 5 e 8, sempre em legendas de figura — os
fragmentos mais curtos do documento, onde o modelo confundia a instrução com o
conteúdo. Em outra legenda os quatro rótulos viraram, todos, o título de uma
seção: `4.3. Detecção de Objetos em PASCAL e MS COCO`.

Comparação direta na mesma legenda, antes e depois da troca de motor descrita em
[§5.3](#53-o-caminho-de-instruções-do-motor-não-serve-a-este-modelo):

| Rótulo esperado | Motor anterior | Motor por linha de comando |
|---|---|---|
| `plain-20` | `4.3. Detecção de Objetos em PASCAL e MS COCO` | `plain-20` |
| `plain-32` | `4.3. Detecção de Objetos em PASCAL e MS COCO` | `plain-32` |
| `plain-44` | `4.3. Detecção de Objetos em PASCAL e MS COCO` | `plain-44` |
| `plain-56` | `4.3. Detecção de Objetos em PASCAL e MS COCO` | `plain-56` |

E o mesmo artigo de 12 páginas caiu de **1.073 s para 452 s — 58% mais rápido**,
porque somem as 533 tentativas estruturadas que falhavam antes de cair no
caminho alternativo.

#### O modelo repete o invólucro de destino

Ao trocar de motor, apareceu um segundo defeito, este vindo **do modelo** e não
da biblioteca. Diante de fragmentos curtos delimitados, o Hy-MT2 responde na
convenção com que foi treinado:

| Entrada | Resposta do modelo |
|---|---|
| `plain-20` | `<target_text>plain-20</target_text>` |
| `error (%)` | `<targetText>erro (%)</targetText>` |
| `56-layer` | `56 camadas` |

Tirar a delimitação `<source_text>` da instrução resolveria, mas ela existe para
que o texto do documento não seja lido como ordem. A delimitação foi mantida e a
resposta passou a ser limpa em `limpar_resposta`, em
[`tradutor/instrucoes.py`](../tradutor/instrucoes.py). O comando `texto` sofria
do mesmo problema e foi corrigido junto.

### 5.7 Tratamento de erros

| Situação | Comportamento verificado |
|---|---|
| Arquivo que não é PDF, com extensão `.pdf` | Recusado pela assinatura do conteúdo |
| PDF truncado | Recusado ao abrir a estrutura |
| PDF protegido por senha | Recusado com orientação |
| PDF com restrição de cópia | Recusado |
| PDF digitalizado | Recusado, com a explicação de que esta versão atende PDFs digitais |
| Páginas mistas | Aceito, com aviso indicando as páginas sem texto |
| Modelo indisponível | Erro claro, com orientação para iniciar o Docker e preparar |
| Resposta fora do formato | Recusada em vez de aceita parcialmente |
| Tradução interrompida por limite de saída | Tratada como falha, não como sucesso |
| Segunda tradução simultânea | Recusada com "já existe uma tradução em andamento" |
| Cancelamento | Libera o bloqueio e não deixa resultado publicado |
| Tempo excedido | Interrompe e libera o bloqueio |
| Aplicação reiniciada no meio | Tarefa marcada como interrompida ao voltar |

## 6. Fontes

- Modelo: <https://huggingface.co/tencent/Hy-MT2-1.8B-GGUF> — arquivo
  `Hy-MT2-1.8B-Q8_0.gguf`, revisão `1cd5208700acedef4ef93019b6cfc148b8522d45`,
  1.908.528.192 bytes, SHA-256
  `5c3fe0b1408a5ceb0143184ef247b11b579c525f4b02b060e6c851bb76fef1a4`.
- API de integração do PDFMathTranslate-next:
  <https://pdf2zh-next.com/advanced/API/python.html>
- Versões fixadas: `pdf2zh-next==2.9.0`, `babeldoc==0.6.2`, `pymupdf==1.25.2`,
  `fastapi==0.115.12`, imagem `ollama/ollama:0.33.3`, Python 3.12.
- Artigos usados na validação, ambos públicos no arXiv:
  [1512.03385](https://arxiv.org/abs/1512.03385) (duas colunas) e
  [1706.03762](https://arxiv.org/abs/1706.03762) (uma coluna). Ficam em
  `entrada/`, fora do controle de versão.

## 7. O que ainda não foi verificado

- **Comparação com o TranslateGemma 4B.** Deixou de ser necessária para corrigir
  o vazamento de instruções, resolvido em §5.3, mas continua interessante para
  comparar qualidade de tradução.
- **Avaliação da tradução por um leitor da área**, para além da inspeção de
  trechos feita aqui.
- **Artigos com tabelas densas** e com notação matemática pesada ao longo de
  todo o texto.
- **Q4_K_M**, que reduziria a memória ao custo de precisão. A medição de §5.1
  mostra que não há necessidade no equipamento atual.
