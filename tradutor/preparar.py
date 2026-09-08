"""Download verificável e importação do modelo oficial. Só esta etapa usa a internet."""

import argparse
import hashlib
import json
import subprocess
import urllib.request
from pathlib import Path

from tradutor.config import Config

REPOSITORIO = "tencent/Hy-MT2-1.8B-GGUF"
REVISAO = "1cd5208700acedef4ef93019b6cfc148b8522d45"
ARQUIVO = "Hy-MT2-1.8B-Q8_0.gguf"
SHA256 = "5c3fe0b1408a5ceb0143184ef247b11b579c525f4b02b060e6c851bb76fef1a4"
TAMANHO = 1908528192
URL = f"https://huggingface.co/{REPOSITORIO}/resolve/{REVISAO}/{ARQUIVO}"
# Conversão direta do chat_template.jinja oficial para o formato de template do Ollama.
TEMPLATE = (
    '<｜hy_begin▁of▁sentence｜>{{ if .System }}{{ .System }}'
    '<｜hy_place▁holder▁no▁3｜>{{ end }}'
    '{{ range .Messages }}{{ if eq .Role "user" }}<｜hy_User｜>{{ .Content }}'
    '{{ else if eq .Role "assistant" }}<｜hy_Assistant｜>{{ .Content }}'
    '<｜hy_place▁holder▁no▁2｜>{{ end }}{{ end }}<｜hy_Assistant｜>'
)


def baixar_modelo(diretorio: Path) -> Path:
    diretorio.mkdir(parents=True, exist_ok=True)
    destino = diretorio / ARQUIVO
    parcial = diretorio / (ARQUIVO + ".part")
    if not destino.exists():
        offset = parcial.stat().st_size if parcial.exists() else 0
        headers = {"User-Agent": "tradutor-artigos/0.1"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        request = urllib.request.Request(URL, headers=headers)
        with urllib.request.urlopen(request, timeout=60) as response:
            append = offset > 0 and response.status == 206
            recebido = offset if append else 0
            ultimo = recebido // (100 * 1024 * 1024)
            with parcial.open("ab" if append else "wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
                    recebido += len(chunk)
                    marco = recebido // (100 * 1024 * 1024)
                    if marco > ultimo:
                        print(f"Modelo: {recebido / TAMANHO:.0%} baixado", flush=True)
                        ultimo = marco
        destino_verificacao = parcial
    else:
        destino_verificacao = destino
    with destino_verificacao.open("rb") as arquivo:
        digest = hashlib.file_digest(arquivo, "sha256").hexdigest()
    if digest != SHA256 or destino_verificacao.stat().st_size != TAMANHO:
        raise ValueError("O arquivo do modelo não corresponde ao SHA-256 oficial. Não será importado.")
    if destino_verificacao == parcial:
        parcial.replace(destino)
    print("Modelo oficial: tamanho e SHA-256 conferidos.", flush=True)
    return destino


def importar_modelo(config: Config, caminho: Path) -> None:
    import httpx

    digest = f"sha256:{SHA256}"
    with httpx.Client(base_url=config.ollama_host, timeout=600, trust_env=False) as client:
        response = client.head(f"/api/blobs/{digest}")
        if response.status_code == 404:
            print("Importando os pesos no armazenamento próprio do Ollama...", flush=True)
            with caminho.open("rb") as arquivo:
                response = client.post(
                    f"/api/blobs/{digest}",
                    content=iter(lambda: arquivo.read(1024 * 1024), b""),
                    headers={"Content-Length": str(TAMANHO)},
                )
        response.raise_for_status()
        response = client.post(
            "/api/create",
            json={
                "model": config.modelo,
                "files": {ARQUIVO: digest},
                "template": TEMPLATE,
                "parameters": {
                    "num_ctx": config.contexto,
                    "num_predict": config.max_saida_tokens,
                    "temperature": 0,
                    "top_k": 20,
                    "top_p": 0.6,
                    "repeat_penalty": 1.05,
                    "stop": ["<｜hy_place▁holder▁no▁2｜>", "<｜hy_place▁holder▁no▁8｜>"],
                },
                "license": "Apache-2.0; https://huggingface.co/tencent/Hy-MT2-1.8B-GGUF",
                "stream": False,
            },
        )
        response.raise_for_status()
        if response.json().get("status") != "success":
            raise ValueError(f"Ollama não confirmou a importação: {response.text}")
    print(f"Modelo pronto: {config.modelo}", flush=True)


def preparar(config: Config, somente_baixar: bool = False) -> None:
    caminho = baixar_modelo(config.dados / "modelos")
    if somente_baixar:
        return
    importar_modelo(config, caminho)
    print("Preparando fontes e modelos de leitura do PDF...", flush=True)
    subprocess.run(["pdf2zh_next", "--warmup"], check=True)
    comprovante = {
        "modelo": config.modelo,
        "repositorio": REPOSITORIO,
        "revisao": REVISAO,
        "sha256": SHA256,
        "contexto": config.contexto,
    }
    (config.dados / "preparacao.json").write_text(
        json.dumps(comprovante, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("Preparação concluída. Traduções posteriores podem funcionar sem internet.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--somente-baixar", action="store_true")
    args = parser.parse_args()
    preparar(Config.ambiente(), args.somente_baixar)
