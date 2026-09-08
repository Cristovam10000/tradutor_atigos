"""Interface web local, com consulta de progresso e downloads controlados."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from tradutor.config import Config
from tradutor.erros import ErroTraducao, Ocupado
from tradutor.pdf import inspecionar_pdf
from tradutor.servico import ServicoTraducao
from tradutor.tarefas import GerenciadorTarefas, Tarefa


def criar_app(config: Config | None = None, servico: ServicoTraducao | None = None) -> FastAPI:
    config = config or Config.ambiente()
    servico = servico or ServicoTraducao(config)
    gerente = GerenciadorTarefas(servico)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        gerente.restaurar()
        yield
        await gerente.encerrar()

    app = FastAPI(title="Tradutor de artigos", version="0.1.0", lifespan=lifespan)
    app.state.gerente = gerente
    estaticos = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=estaticos), name="static")

    @app.get("/", include_in_schema=False)
    async def inicio() -> FileResponse:
        return FileResponse(estaticos / "index.html")

    @app.get("/saude")
    async def saude() -> dict:
        try:
            await servico.modelo.verificar()
            return {"aplicacao": "ok", "modelo": "pronto", "nome_modelo": config.modelo}
        except ErroTraducao as exc:
            return {"aplicacao": "ok", "modelo": "indisponivel", "mensagem": str(exc)}

    @app.post("/api/traducoes", status_code=202, response_model=Tarefa)
    async def criar_traducao(
        request: Request, arquivo: Annotated[UploadFile, File()]
    ) -> Tarefa:
        if gerente.ativa and not gerente.ativa.done():
            await arquivo.close()
            raise HTTPException(409, "Já existe uma tradução em andamento.")
        tamanho = request.headers.get("content-length")
        if tamanho and tamanho.isdigit() and int(tamanho) > config.max_bytes + 1024 * 1024:
            await arquivo.close()
            raise HTTPException(413, "O limite por arquivo é de 50 MB.")
        nome = Path((arquivo.filename or "artigo.pdf").replace("\\", "/")).name
        if Path(nome).suffix.lower() != ".pdf":
            await arquivo.close()
            raise HTTPException(400, "Envie um arquivo PDF.")
        identificador = str(uuid4())
        entradas = config.dados / "entradas"
        entradas.mkdir(exist_ok=True)
        destino = entradas / f"{identificador}.pdf"
        try:
            recebido = 0
            with destino.open("xb") as output:
                while bloco := await arquivo.read(1024 * 1024):
                    recebido += len(bloco)
                    if recebido > config.max_bytes:
                        raise HTTPException(413, "O limite por arquivo é de 50 MB.")
                    output.write(bloco)
            await asyncio.to_thread(inspecionar_pdf, destino, config)
            return gerente.iniciar(identificador, nome, destino)
        except HTTPException:
            destino.unlink(missing_ok=True)
            raise
        except ErroTraducao as exc:
            destino.unlink(missing_ok=True)
            raise HTTPException(409 if isinstance(exc, Ocupado) else 400, str(exc)) from exc
        finally:
            await arquivo.close()

    def obter(id_tarefa: str) -> Tarefa:
        try:
            return gerente.buscar(id_tarefa)
        except KeyError as exc:
            raise HTTPException(404, "Tarefa não encontrada.") from exc

    @app.get("/api/traducoes/{id_tarefa}", response_model=Tarefa)
    async def consultar(id_tarefa: str) -> Tarefa:
        return obter(id_tarefa)

    @app.post("/api/traducoes/{id_tarefa}/cancelar", response_model=Tarefa)
    async def cancelar(id_tarefa: str) -> Tarefa:
        obter(id_tarefa)
        return await gerente.cancelar(id_tarefa)

    @app.get("/api/traducoes/{id_tarefa}/arquivos/{tipo}")
    async def baixar(id_tarefa: str, tipo: Literal["traduzido", "bilingue"]) -> FileResponse:
        tarefa = obter(id_tarefa)
        if tarefa.estado != "concluida" or not tarefa.resultado:
            raise HTTPException(409, "Os arquivos ainda não estão disponíveis.")
        caminho = Path(tarefa.resultado[tipo]).resolve()
        raiz = (config.dados / "resultados" / id_tarefa).resolve()
        if not caminho.is_relative_to(raiz) or not caminho.is_file():
            raise HTTPException(404, "Arquivo não encontrado.")
        return FileResponse(caminho, media_type="application/pdf", filename=f"artigo-{tipo}.pdf")

    return app
