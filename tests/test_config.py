import pytest

from tradutor.config import Config


@pytest.mark.parametrize("url", [
    "https://api.openai.com", "http://8.8.8.8", "http://user:password@localhost:11434",
])
def test_provedor_externo_nao_pode_ser_configurado(url):
    with pytest.raises(ValueError, match="local"):
        Config(ollama_host=url)
