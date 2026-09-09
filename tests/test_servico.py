import asyncio
import logging
from dataclasses import replace
from types import SimpleNamespace

import pytest
from conftest import criar_pdf

from tradutor.erros import ErroTraducao, Ocupado, PDFInvalido, TempoExcedido
from tradutor.motor_pdf import configuracao_motor
from tradutor.pdf import hash_arquivo
from tradutor.servico import ServicoTraducao


class ModeloSimulado:
    async def verificar(self):
        return {"model_info": {}}


class MotorSimulado:
    def __init__(self, modo="sucesso"):
        self.modo = modo
        self.finalizou = False
        self.iniciou = asyncio.Event()

    async def eventos(self, entrada, saida):
        self.iniciou.set()
        try:
            if self.modo == "esperar":
                await asyncio.sleep(60)
            if self.modo == "avisando":
                logging.getLogger("babeldoc.pdf").warning("Fonte ausente na página 1")
            saida.mkdir(parents=True)
            mono = criar_pdf(saida / "mono.pdf")
            dual = criar_pdf(saida / "dual.pdf", 2 if self.modo != "invalido" else 1)
            yield {
                "type": "progress_update",
                "stage": "Translate Paragraphs",
                "overall_progress": 50,
            }
            if self.modo == "erro":
                yield {"type": "error", "error": "falha simulada após gravar arquivos"}
            elif self.modo != "sem_finish":
                yield {"type": "finish", "translate_result": SimpleNamespace(
                    mono_pdf_path=mono, dual_pdf_path=dual,
                )}
        finally:
            self.finalizou = True


async def consumir(servico, pdf, saida):
    return [evento async for evento in servico.traduzir_pdf(pdf, saida)]


async def test_sucesso_preserva_original_e_publica_par(pdf, config, tmp_path):
    original = hash_arquivo(pdf)
    servico = ServicoTraducao(config, ModeloSimulado(), MotorSimulado())
    eventos = await consumir(servico, pdf, tmp_path / "saida")
    result = eventos[-1].resultado
    assert result.paginas == 1
    assert result.sha256_original == original == hash_arquivo(pdf)
    assert len(list((tmp_path / "saida").rglob("*.pdf"))) == 2
    assert result.avisos
    assert eventos[-1].progresso == 100


@pytest.mark.parametrize("modo", ["erro", "sem_finish", "invalido"])
async def test_arquivos_existentes_nao_bastam_para_sucesso(pdf, config, tmp_path, modo):
    servico = ServicoTraducao(config, ModeloSimulado(), MotorSimulado(modo))
    with pytest.raises((ErroTraducao, PDFInvalido)):
        await consumir(servico, pdf, tmp_path / "saida")
    assert not list((tmp_path / "saida").rglob("*.pdf"))


async def test_aviso_do_motor_chega_ao_resultado(pdf, config, tmp_path):
    servico = ServicoTraducao(config, ModeloSimulado(), MotorSimulado("avisando"))
    eventos = await consumir(servico, pdf, tmp_path / "saida")
    assert "Fonte ausente na página 1" in eventos[-1].resultado.avisos


async def test_registro_de_avisos_e_removido_ao_final(pdf, config, tmp_path):
    servico = ServicoTraducao(config, ModeloSimulado(), MotorSimulado("avisando"))
    await consumir(servico, pdf, tmp_path / "saida")
    assert not list((config.dados / "trabalho").glob("avisos-*.log"))


async def test_bloqueio_entre_instancias(pdf, config, tmp_path):
    servico = ServicoTraducao(config, ModeloSimulado(), MotorSimulado())
    with servico.bloqueio():
        outro = ServicoTraducao(config, ModeloSimulado(), MotorSimulado())
        with pytest.raises(Ocupado):
            await consumir(outro, pdf, tmp_path / "saida")


async def test_cancelamento_libera_recursos(pdf, config, tmp_path):
    motor = MotorSimulado("esperar")
    servico = ServicoTraducao(config, ModeloSimulado(), motor)
    tarefa = asyncio.create_task(consumir(servico, pdf, tmp_path / "saida"))
    await motor.iniciou.wait()
    tarefa.cancel()
    with pytest.raises(asyncio.CancelledError):
        await tarefa
    assert motor.finalizou
    with servico.bloqueio():
        pass
    assert not list((tmp_path / "saida").rglob("*.pdf"))


async def test_timeout_libera_bloqueio(pdf, config, tmp_path):
    config = replace(config, timeout_tarefa=0.1)
    servico = ServicoTraducao(config, ModeloSimulado(), MotorSimulado("esperar"))
    with pytest.raises(TempoExcedido):
        await consumir(servico, pdf, tmp_path / "saida")
    with servico.bloqueio():
        pass


def test_configuracao_real_do_motor_e_local(config, tmp_path):
    settings = configuracao_motor(config, tmp_path)
    settings.validate_settings()
    assert settings.translate_engine_settings.openai_base_url == "http://modelo:11434/v1"
    assert settings.translation.pool_max_workers == 1
    assert settings.translation.no_auto_extract_glossary
    assert settings.pdf.use_alternating_pages_dual
    assert settings.pdf.translate_table_text
    assert settings.pdf.disable_rich_text_translate
