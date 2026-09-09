"""Adaptação da API recomendada do PDFMathTranslate, sem alterar a biblioteca."""

import shlex
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from tradutor.config import Config


def comando_tradutor(config: Config) -> str:
    """Comando que o motor executa uma vez por trecho, enviando o texto por stdin.

    Servidor e modelo seguem explícitos: a configuração deste processo é a que
    vale, e não o ambiente que o processo filho venha a herdar.
    """
    return shlex.join([
        sys.executable,
        "-m",
        "tradutor.traduzir_trecho",
        "--servidor",
        config.ollama_host,
        "--modelo",
        config.modelo,
    ])


def configuracao_motor(config: Config, saida: Path) -> Any:
    # Importação tardia: consultar ajuda ou traduzir texto não precisa carregar o motor de PDF.
    from pdf2zh_next.config.model import PDFSettings, SettingsModel, TranslationSettings
    from pdf2zh_next.config.translate_engine_model import CLISettings

    return SettingsModel(
        translation=TranslationSettings(
            lang_in="en",
            lang_out="pt",
            output=str(saida),
            qps=1,
            pool_max_workers=1,
            no_auto_extract_glossary=True,
        ),
        pdf=PDFSettings(
            no_mono=False,
            no_dual=False,
            use_alternating_pages_dual=True,
            # O modelo é especializado em traduzir, e não em reproduzir marcações.
            # Pedir estilo dentro do parágrafo faz vazar marcadores como "{v1>" no PDF.
            disable_rich_text_translate=True,
            watermark_output_mode="no_watermark",
            translate_table_text=True,
            auto_enable_ocr_workaround=False,
        ),
        # Motor por linha de comando, escolhido por uma razão medida. Aos motores que
        # falam com modelos de instrução, a biblioteca envia um bloco de regras junto
        # do texto; um tradutor puro traduz essas regras, e elas foram parar dentro do
        # PDF no lugar das legendas. Este motor recebe apenas o texto, e a instrução
        # fica sob nosso controle, em tradutor/instrucoes.py.
        translate_engine_settings=CLISettings(
            clitranslator_command=comando_tradutor(config),
            clitranslator_timeout=min(300, max(1, int(config.timeout_modelo))),
        ),
    )


class MotorPDF:
    def __init__(self, config: Config):
        self.config = config

    async def eventos(self, entrada: Path, saida: Path) -> AsyncIterator[dict[str, Any]]:
        from pdf2zh_next.high_level import do_translate_async_stream

        settings = configuracao_motor(self.config, saida)
        async for evento in do_translate_async_stream(settings, entrada):
            yield evento


def nome_etapa(etapa: str) -> str:
    nomes = {
        "Parse PDF and Create Intermediate Representation": "Lendo a estrutura do PDF",
        "DetectScannedFile": "Verificando texto selecionável",
        "Parse Page Layout": "Identificando a diagramação",
        "Translate Paragraphs": "Traduzindo os parágrafos",
        "Save PDF": "Gravando os PDFs",
        "Typesetting": "Ajustando a diagramação",
        "ParagraphFinder": "Organizando os parágrafos",
        "Detect Tables": "Identificando as tabelas",
    }
    return nomes.get(etapa, f"Processando documento: {etapa}")
