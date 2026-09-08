"""Estado persistente das tarefas web; arquivos existentes não significam sucesso."""

import asyncio
import logging
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from tradutor.erros import ErroTraducao, Ocupado
from tradutor.servico import ServicoTraducao, gravar_json

logger = logging.getLogger(__name__)
Estado = Literal["aguardando", "processando", "concluida", "falhou", "cancelada", "interrompida"]


class Tarefa(BaseModel):
    id: str
    nome: str
    estado: Estado = "aguardando"
    etapa: str = "Aguardando processamento"
    progresso: float = 0
    criado_em: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    erro: str | None = None
    codigo_erro: str | None = None
    resultado: dict | None = None


class GerenciadorTarefas:
    def __init__(self, servico: ServicoTraducao):
        self.servico = servico
        self.pasta = servico.config.dados / "tarefas"
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.ativa: asyncio.Task | None = None
        self.id_ativa: str | None = None
        self.tarefas: dict[str, Tarefa] = {}

    def restaurar(self) -> None:
        for arquivo in self.pasta.glob("*.json"):
            try:
                tarefa = Tarefa.model_validate_json(arquivo.read_text(encoding="utf-8"))
                if tarefa.estado in {"aguardando", "processando"}:
                    tarefa.estado = "interrompida"
                    tarefa.etapa = "A aplicação foi reiniciada; envie o arquivo novamente"
                    self.salvar(tarefa)
                self.tarefas[tarefa.id] = tarefa
            except (ValueError, OSError):
                logger.exception("Não foi possível restaurar o registro %s", arquivo.name)

    def salvar(self, tarefa: Tarefa) -> None:
        gravar_json(self.pasta / f"{tarefa.id}.json", tarefa.model_dump())

    def buscar(self, id_tarefa: str) -> Tarefa:
        try:
            UUID(id_tarefa)
            return self.tarefas[id_tarefa]
        except (ValueError, KeyError) as exc:
            raise KeyError("Tarefa não encontrada") from exc

    def iniciar(self, id_tarefa: str, nome: str, entrada: Path) -> Tarefa:
        if self.ativa is not None and not self.ativa.done():
            raise Ocupado("Já existe uma tradução em andamento.")
        tarefa = Tarefa(id=id_tarefa, nome=nome)
        self.tarefas[tarefa.id] = tarefa
        self.salvar(tarefa)
        self.id_ativa = tarefa.id
        self.ativa = asyncio.create_task(self._executar(tarefa, entrada))
        return tarefa

    async def _executar(self, tarefa: Tarefa, entrada: Path) -> None:
        try:
            tarefa.estado = "processando"
            self.salvar(tarefa)
            async for evento in self.servico.traduzir_pdf(
                entrada, self.servico.config.dados / "resultados" / tarefa.id
            ):
                tarefa.etapa = evento.etapa
                tarefa.progresso = evento.progresso
                if evento.resultado:
                    tarefa.resultado = asdict(evento.resultado)
                    tarefa.estado = "concluida"
                self.salvar(tarefa)
        except asyncio.CancelledError:
            tarefa.estado = "cancelada"
            tarefa.etapa = "Tradução cancelada"
            self.salvar(tarefa)
        except ErroTraducao as exc:
            tarefa.estado = "falhou"
            tarefa.erro = str(exc)
            tarefa.codigo_erro = exc.codigo
            tarefa.etapa = "Não foi possível concluir a tradução"
            self.salvar(tarefa)
        except Exception:
            logger.exception("Erro inesperado na tarefa %s", tarefa.id)
            tarefa.estado = "falhou"
            tarefa.erro = "Erro inesperado. Consulte os logs da aplicação."
            tarefa.codigo_erro = "erro_interno"
            self.salvar(tarefa)

    async def cancelar(self, id_tarefa: str) -> Tarefa:
        tarefa = self.buscar(id_tarefa)
        if self.id_ativa == id_tarefa and self.ativa and not self.ativa.done():
            self.ativa.cancel()
            await self.ativa
        return tarefa

    async def encerrar(self) -> None:
        if self.ativa and not self.ativa.done():
            self.ativa.cancel()
            await self.ativa
