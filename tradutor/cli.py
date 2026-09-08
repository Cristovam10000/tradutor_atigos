import argparse
import asyncio
import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path

from filelock import Timeout

from tradutor.config import Config
from tradutor.erros import ErroTraducao, Ocupado
from tradutor.modelo import ClienteModelo
from tradutor.servico import ServicoTraducao


async def executar(args: argparse.Namespace, config: Config) -> None:
    servico = ServicoTraducao(config)
    if args.comando == "texto":
        try:
            with servico.bloqueio():
                await servico.modelo.verificar()
                resultado = await servico.modelo.traduzir_texto(args.texto)
        except Timeout as exc:
            raise Ocupado("Já existe uma tradução em andamento.") from exc
        if args.json:
            print(json.dumps(asdict(resultado), ensure_ascii=False, indent=2))
        else:
            print(resultado.texto)
            print(f"\nTempo: {resultado.segundos}s", file=sys.stderr)
    elif args.comando == "traduzir":
        ultimo = ""
        async for evento in servico.traduzir_pdf(args.arquivo, args.saida):
            mensagem = f"{evento.progresso:5.1f}% | {evento.etapa}"
            if mensagem != ultimo:
                print(mensagem, file=sys.stderr, flush=True)
                ultimo = mensagem
            if evento.resultado:
                print(json.dumps(asdict(evento.resultado), ensure_ascii=False, indent=2))
    elif args.comando == "diagnostico":
        info = await ClienteModelo(config).verificar()
        print(json.dumps({
            "modelo": config.modelo,
            "servidor": config.ollama_host,
            "parametros": info.get("parameters"),
            "detalhes": info.get("details"),
            "preparacao_recursos": (config.dados / "preparacao.json").is_file(),
        }, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Tradução local de artigos: inglês -> português.")
    comandos = parser.add_subparsers(dest="comando", required=True)
    comandos.add_parser("preparar", help="Baixar, verificar e preparar modelo e recursos de PDF")
    comandos.add_parser("diagnostico", help="Verificar a disponibilidade do modelo local")
    texto = comandos.add_parser("texto", help="Traduzir um trecho de até 6000 caracteres")
    texto.add_argument("texto")
    texto.add_argument("--json", action="store_true", help="Mostrar tradução e métricas em JSON")
    pdf = comandos.add_parser("traduzir", help="Traduzir um PDF digital")
    pdf.add_argument("arquivo", type=Path)
    pdf.add_argument("--saida", type=Path, default=Path("resultados"))
    web = comandos.add_parser("servir", help="Abrir a aplicação web local")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        config = Config.ambiente()
        if args.comando == "preparar":
            from tradutor.preparar import preparar

            preparar(config)
        elif args.comando == "servir":
            import uvicorn

            from tradutor.web import criar_app

            uvicorn.run(criar_app(config), host=args.host, port=args.port)
        else:
            asyncio.run(executar(args, config))
    except (ErroTraducao, ValueError, OSError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except KeyboardInterrupt:
        print("\nOperação interrompida pelo usuário.", file=sys.stderr)
        raise SystemExit(130) from None
