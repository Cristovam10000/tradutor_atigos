"""O usuário precisa ver o que o motor relatou, mesmo vindo de outro processo."""

import logging
import os
import sys

import pytest

from tradutor.servico import ColetorAvisos


@pytest.fixture
def coletor(tmp_path):
    handler = ColetorAvisos(tmp_path / "avisos.log")
    logging.getLogger().addHandler(handler)
    logging.getLogger("babeldoc").setLevel(logging.INFO)
    yield handler
    logging.getLogger().removeHandler(handler)


def test_aviso_do_motor_e_recolhido(coletor):
    logging.getLogger("babeldoc.pdf").warning("Fonte ausente na página 3")
    logging.getLogger("outra.biblioteca").warning("ruído que não interessa")
    assert coletor.mensagens() == ["Fonte ausente na página 3"]


def test_informacao_comum_do_motor_e_ignorada(coletor):
    logging.getLogger("babeldoc.pdf").info("Parse PDF and Create Intermediate Representation")
    assert coletor.mensagens() == []


def test_resumo_de_recurso_vira_aviso_em_portugues(coletor):
    logging.getLogger("babeldoc.pdf").info(
        "Translation completed. Total: 56, Successful: 0, Fallback: 56"
    )
    assert "56 de 56 trechos usaram a tradução simples" in coletor.mensagens()[0]


def test_resumo_sem_recurso_nao_gera_aviso(coletor):
    logging.getLogger("babeldoc.pdf").info(
        "Translation completed. Total: 56, Successful: 56, Fallback: 0"
    )
    assert coletor.mensagens() == []


def test_mensagem_repetida_aparece_uma_vez(coletor):
    for _ in range(5):
        logging.getLogger("babeldoc.pdf").warning("Erro ao traduzir parágrafo")
    assert coletor.mensagens() == ["Erro ao traduzir parágrafo"]


@pytest.mark.skipif(not hasattr(os, "fork"), reason="exige fork, como no contêiner Linux")
def test_aviso_emitido_em_processo_filho_chega_ao_pai(coletor):
    """O motor de PDF roda em um processo filho: a lista em memória não bastaria."""
    if os.fork() == 0:  # pragma: no cover - executa apenas no processo filho
        logging.getLogger("babeldoc.pdf").warning("Aviso vindo do processo filho")
        os._exit(0)
    _, status = os.wait()
    assert os.waitstatus_to_exitcode(status) == 0
    assert coletor.mensagens() == ["Aviso vindo do processo filho"]


def test_falha_de_escrita_nao_interrompe_a_traducao(tmp_path):
    handler = ColetorAvisos(tmp_path / "sem-pasta" / "avisos.log")
    logging.getLogger().addHandler(handler)
    try:
        logging.getLogger("babeldoc.pdf").warning("aviso que não pode ser gravado")
    finally:
        logging.getLogger().removeHandler(handler)
    assert handler.mensagens() == []
    assert sys.exc_info() == (None, None, None)
