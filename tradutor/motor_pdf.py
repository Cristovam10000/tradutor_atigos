"""Adaptação da API recomendada do PDFMathTranslate, sem alterar a biblioteca."""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from tradutor.config import Config

INSTRUCAO = (
    "Translate into Brazilian Portuguese, using scientific and technical terminology. "
    "Preserve all numbers, equations, citation identifiers, code and placeholder tags. "
    "Do not summarize, omit content or add commentary. "
    "Follow the requested output structure exactly."
)


def configuracao_motor(config: Config, saida: Path) -> Any:
    # Importação tardia: consultar ajuda ou traduzir texto não precisa carregar o motor de PDF.
    from pdf2zh_next.config.model import PDFSettings, SettingsModel, TranslationSettings
    from pdf2zh_next.config.translate_engine_model import OpenAISettings

    return SettingsModel(
        translation=TranslationSettings(
            lang_in="en",
            lang_out="pt",
            output=str(saida),
            qps=1,
            pool_max_workers=1,
            no_auto_extract_glossary=True,
            custom_system_prompt=INSTRUCAO,
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
        # O formato de comunicação é compatível com OpenAI, mas o destino é SOMENTE
        # o Ollama local. A chave abaixo é um texto fictício exigido pela biblioteca.
        translate_engine_settings=OpenAISettings(
            openai_model=config.modelo,
            openai_base_url=f"{config.ollama_host}/v1",
            openai_api_key="local-only",
            openai_timeout=str(config.timeout_modelo),
            openai_send_temprature=True,
            openai_temperature="0",
            openai_enable_json_mode=False,
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
