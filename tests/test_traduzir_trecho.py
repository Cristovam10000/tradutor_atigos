"""O motor executa este comando uma vez por trecho: falhas não podem passar caladas."""

import io
import json
import urllib.error

import pytest

from tradutor.instrucoes import limpar_resposta
from tradutor.traduzir_trecho import LIMITE_CARACTERES, configurar, main, traduzir


class RespostaFalsa(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def responder(monkeypatch, corpo: dict, registro: list | None = None):
    def urlopen(requisicao, timeout=None):
        if registro is not None:
            registro.append(json.loads(requisicao.data))
        return RespostaFalsa(json.dumps(corpo).encode())

    monkeypatch.setattr("tradutor.traduzir_trecho.urllib.request.urlopen", urlopen)


def resposta_ok(conteudo: str) -> dict:
    return {"message": {"content": conteudo}, "done": True, "done_reason": "stop"}


def test_envia_instrucao_e_limites(config, monkeypatch):
    enviados: list = []
    responder(monkeypatch, resposta_ok("Redes residuais profundas"), enviados)
    assert traduzir("Deep residual networks", config) == "Redes residuais profundas"
    corpo = enviados[0]
    assert corpo["model"] == config.modelo
    assert corpo["options"]["num_ctx"] == 8192
    assert "Brazilian Portuguese" in corpo["messages"][0]["content"]
    assert "Deep residual networks" in corpo["messages"][0]["content"]


def test_involucro_de_destino_e_removido(config, monkeypatch):
    responder(monkeypatch, resposta_ok("<targetText>\nplain-20\n</targetText>"))
    assert traduzir("plain-20", config) == "plain-20"


@pytest.mark.parametrize("corpo", [
    {"message": {"content": "parcial"}, "done": True, "done_reason": "length"},
    {"message": {"content": "   "}, "done": True},
    {"message": {"content": "algo"}, "done": False},
    {"message": {"content": 17}, "done": True},
    {"erro": "formato inesperado"},
])
def test_resposta_invalida_e_recusada(config, monkeypatch, corpo):
    responder(monkeypatch, corpo)
    with pytest.raises(ValueError):
        traduzir("Deep residual networks", config)


def test_trecho_vazio_nao_chama_o_modelo(monkeypatch, capsys):
    def proibido(*_, **__):
        raise AssertionError("o modelo não deveria ser chamado")

    monkeypatch.setattr("tradutor.traduzir_trecho.urllib.request.urlopen", proibido)
    monkeypatch.setattr("sys.stdin", io.StringIO("   \n"))
    main([])
    assert capsys.readouterr().out == ""


def test_trecho_longo_demais_falha(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("x" * (LIMITE_CARACTERES + 1)))
    with pytest.raises(SystemExit) as saida:
        main([])
    assert saida.value.code == 1
    assert str(LIMITE_CARACTERES) in capsys.readouterr().err


def test_falha_de_rede_encerra_com_erro(monkeypatch, capsys):
    def cair(*_, **__):
        raise urllib.error.URLError("modelo fora do ar")

    monkeypatch.setattr("tradutor.traduzir_trecho.urllib.request.urlopen", cair)
    monkeypatch.setattr("sys.stdin", io.StringIO("Deep residual networks"))
    with pytest.raises(SystemExit) as saida:
        main([])
    # Encerrar com erro faz o motor repetir e registrar; o silêncio publicaria
    # o texto original como se estivesse traduzido.
    assert saida.value.code == 1
    assert "Falha ao traduzir" in capsys.readouterr().err


def test_argumentos_definem_servidor_e_modelo():
    config = configurar(["--servidor", "http://modelo:11434", "--modelo", "outro:q4"])
    assert config.ollama_host == "http://modelo:11434"
    assert config.modelo == "outro:q4"


def test_servidor_externo_e_recusado_tambem_aqui():
    with pytest.raises(ValueError, match="local"):
        configurar(["--servidor", "https://api.openai.com"])


@pytest.mark.parametrize("bruto, esperado", [
    ("<targetText>\nerro (%)\n</targetText>", "erro (%)"),
    ("<target_text>\nplain-20\n</target_text>", "plain-20"),
    ("<TargetText>std</TargetText>", "std"),
    ("<targetText>\nsem fechamento", "sem fechamento"),
    ("Índice de camada (ordenado por magnitude)", "Índice de camada (ordenado por magnitude)"),
    ("A relação <b>x</b> permanece", "A relação <b>x</b> permanece"),
])
def test_limpeza_da_resposta(bruto, esperado):
    assert limpar_resposta(bruto) == esperado
