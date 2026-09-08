import json

import httpx
import pytest

from tradutor.erros import ModeloIndisponivel, RespostaInvalida
from tradutor.modelo import ClienteModelo


async def test_traducao_envia_limites_e_retorna_metricas(config):
    def responder(request):
        body = json.loads(request.content)
        assert request.url.host == "modelo"
        assert body["options"]["num_ctx"] == 8192
        assert body["options"]["num_predict"] == 4096
        assert "Brazilian Portuguese" in body["messages"][0]["content"]
        return httpx.Response(200, json={
            "message": {"content": "O resultado não foi significativo: p = 0.12."},
            "done": True, "done_reason": "stop", "prompt_eval_count": 80, "eval_count": 20,
        })
    cliente = ClienteModelo(config, httpx.MockTransport(responder))
    result = await cliente.traduzir_texto("The result was not significant: p = 0.12.")
    assert "não" in result.texto
    assert "0.12" in result.texto
    assert result.tokens_saida == 20


@pytest.mark.parametrize("resposta", [
    {"message": {"content": ""}, "done": True},
    {"message": {"content": "parte"}, "done": True, "done_reason": "length"},
    {"message": {"content": 17}, "done": True},
    {"message": {"content": "parte"}, "done": False},
    {"unexpected": "shape"},
])
async def test_rejeita_respostas_invalidas(config, resposta):
    client = ClienteModelo(config, httpx.MockTransport(lambda r: httpx.Response(200, json=resposta)))
    with pytest.raises(RespostaInvalida):
        await client.traduzir_texto("A valid English sentence.")


async def test_servidor_inacessivel(config):
    def falhar(request):
        raise httpx.ConnectError("offline", request=request)
    client = ClienteModelo(config, httpx.MockTransport(falhar))
    with pytest.raises(ModeloIndisponivel):
        await client.verificar()


async def test_modelo_ausente(config):
    client = ClienteModelo(config, httpx.MockTransport(lambda r: httpx.Response(404)))
    with pytest.raises(ModeloIndisponivel):
        await client.verificar()


async def test_texto_longo_nao_e_truncado_silenciosamente(config):
    client = ClienteModelo(config)
    with pytest.raises(RespostaInvalida, match="6000"):
        await client.traduzir_texto("x" * 6001)
