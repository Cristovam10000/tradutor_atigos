"""Traduz um trecho recebido pela entrada padrão; usado pelo motor de PDF.

O motor executa um processo por trecho. Importar httpx e pydantic aqui custaria
cerca de 0,33 s a cada chamada — mais de dois minutos em um artigo com 500
trechos — por isso este módulo conversa com o Ollama pela biblioteca padrão e
valida a resposta por conta própria.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from dataclasses import replace

from tradutor.config import Config
from tradutor.instrucoes import instrucao_traducao, limpar_resposta

# O motor já divide o texto por contagem de tokens. Este limite só recusa uma
# entrada absurda antes de ocupar o modelo com ela.
LIMITE_CARACTERES = 24000


def traduzir(texto: str, config: Config) -> str:
    corpo = json.dumps(
        {
            "model": config.modelo,
            "messages": [{"role": "user", "content": instrucao_traducao(texto)}],
            "stream": False,
            "keep_alive": "5m",
            "options": {
                "num_ctx": config.contexto,
                "num_predict": config.max_saida_tokens,
                "temperature": 0,
                "top_k": 20,
                "top_p": 0.6,
                "repeat_penalty": 1.05,
            },
        }
    ).encode()
    requisicao = urllib.request.Request(
        f"{config.ollama_host}/api/chat",
        data=corpo,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(requisicao, timeout=config.timeout_modelo) as resposta:
        dados = json.load(resposta)
    if not isinstance(dados, dict) or not dados.get("done"):
        raise ValueError("O modelo não confirmou a conclusão da resposta.")
    if dados.get("done_reason") == "length":
        raise ValueError("A tradução foi interrompida pelo limite de saída do modelo.")
    conteudo = dados.get("message", {}).get("content")
    if not isinstance(conteudo, str) or not conteudo.strip():
        raise ValueError("O modelo devolveu uma tradução vazia.")
    return limpar_resposta(conteudo)


def configurar(argumentos: list[str] | None = None) -> Config:
    parser = argparse.ArgumentParser(description="Traduz um trecho recebido por stdin.")
    parser.add_argument("--servidor")
    parser.add_argument("--modelo")
    args = parser.parse_args(argumentos)
    config = Config.ambiente()
    # Config recusa qualquer servidor que não seja local, inclusive aqui.
    return replace(
        config,
        ollama_host=args.servidor or config.ollama_host,
        modelo=args.modelo or config.modelo,
    )


def main(argumentos: list[str] | None = None) -> None:
    texto = sys.stdin.read()
    # O motor envia trechos sem conteúdo traduzível; devolver vazio é o correto.
    if not texto.strip():
        return
    if len(texto) > LIMITE_CARACTERES:
        print(f"Trecho acima de {LIMITE_CARACTERES} caracteres.", file=sys.stderr)
        raise SystemExit(1)
    try:
        print(traduzir(texto, configurar(argumentos)))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        # O motor repete o comando algumas vezes; falhar em silêncio faria o
        # texto original ser publicado como se estivesse traduzido.
        print(f"Falha ao traduzir o trecho: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
