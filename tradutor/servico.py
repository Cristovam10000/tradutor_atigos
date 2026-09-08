"""Um único fluxo de negócio, compartilhado pelo terminal e pela aplicação web."""

import asyncio
import json
import logging
import shutil
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from uuid import uuid4

from filelock import FileLock, Timeout

from tradutor.config import Config
from tradutor.erros import ErroTraducao, Ocupado, PDFInvalido, TempoExcedido
from tradutor.modelo import ClienteModelo
from tradutor.motor_pdf import MotorPDF, nome_etapa
from tradutor.pdf import hash_arquivo, inspecionar_pdf, verificar_saida

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Resultado:
    traduzido: str
    bilingue: str
    paginas: int
    segundos: float
    modelo: str
    sha256_original: str
    avisos: list[str]


@dataclass(frozen=True)
class Evento:
    etapa: str
    progresso: float
    resultado: Resultado | None = None


class ColetorAvisos(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.mensagens: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith(("babeldoc", "pdf2zh_next")):
            mensagem = record.getMessage()[:700]
            if mensagem not in self.mensagens and len(self.mensagens) < 30:
                self.mensagens.append(mensagem)


def gravar_json(caminho: Path, dados: dict) -> None:
    temporario = caminho.with_suffix(".json.tmp")
    temporario.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    temporario.replace(caminho)


class ServicoTraducao:
    def __init__(
        self, config: Config, modelo: ClienteModelo | None = None, motor: MotorPDF | None = None
    ):
        self.config = config
        self.modelo = modelo or ClienteModelo(config)
        self.motor = motor or MotorPDF(config)
        self.config.dados.mkdir(parents=True, exist_ok=True)

    def bloqueio(self) -> FileLock:
        return FileLock(self.config.dados / "traducao.lock", timeout=0, thread_local=False)

    async def traduzir_pdf(self, entrada: Path, saida: Path) -> AsyncIterator[Evento]:
        """Só publica os dois PDFs depois de receber sucesso e validar ambos."""
        lock = self.bloqueio()
        try:
            lock.acquire()
        except Timeout as exc:
            raise Ocupado("Já existe uma tradução em andamento. Aguarde sua conclusão.") from exc
        coletor = ColetorAvisos()
        logging.getLogger().addHandler(coletor)
        try:
            async with asyncio.timeout(self.config.timeout_tarefa):
                async for evento in self._executar(entrada, saida, coletor):
                    yield evento
        except TimeoutError as exc:
            raise TempoExcedido("A tradução excedeu o limite de tempo e foi interrompida.") from exc
        finally:
            logging.getLogger().removeHandler(coletor)
            lock.release()

    async def _executar(
        self, entrada: Path, saida: Path, coletor: ColetorAvisos
    ) -> AsyncIterator[Evento]:
        inicio = monotonic()
        yield Evento("Verificando o arquivo", 0)
        documento = await asyncio.to_thread(inspecionar_pdf, entrada, self.config)
        await self.modelo.verificar()
        avisos = list(documento.avisos)
        saida = saida.resolve()
        trabalho = self.config.dados / "trabalho"
        trabalho.mkdir(exist_ok=True)
        with TemporaryDirectory(prefix="pdf-", dir=trabalho) as pasta:
            temporario = Path(pasta)
            # A biblioteca recebe uma cópia: limpeza/reconstrução jamais toca o original.
            copia = temporario / "artigo.pdf"
            await asyncio.to_thread(shutil.copyfile, documento.caminho, copia)
            artefatos = None
            progresso = 0.0
            try:
                async for evento in self.motor.eventos(copia, temporario / "motor"):
                    tipo = evento.get("type")
                    if tipo == "error":
                        logger.error("Motor PDF: %s", evento.get("error"))
                        raise ErroTraducao(
                            "O motor de PDF informou uma falha. Confira os logs da aplicação."
                        )
                    if tipo in {"progress_start", "progress_update", "progress_end"}:
                        valor = evento.get("overall_progress", 0)
                        if isinstance(valor, (int, float)):
                            progresso = max(progresso, min(95.0, max(0.0, valor) * 0.95))
                        yield Evento(nome_etapa(str(evento.get("stage", "PDF"))), progresso)
                    if tipo == "finish":
                        artefatos = evento.get("translate_result")
                        break
            except asyncio.CancelledError:
                raise
            except ErroTraducao:
                raise
            except Exception as exc:
                logger.exception("Falha no processamento do PDF")
                raise ErroTraducao("Falha ao processar o PDF. Confira os logs da aplicação.") from exc
            if artefatos is None:
                raise ErroTraducao("O motor encerrou sem confirmar a conclusão da tradução.")
            mono = getattr(artefatos, "no_watermark_mono_pdf_path", None) or getattr(
                artefatos, "mono_pdf_path", None
            )
            dual = getattr(artefatos, "no_watermark_dual_pdf_path", None) or getattr(
                artefatos, "dual_pdf_path", None
            )
            if not mono or not dual:
                raise ErroTraducao("O motor não retornou os dois PDFs esperados.")
            yield Evento("Verificando os arquivos gerados", 97)
            await asyncio.to_thread(verificar_saida, Path(mono), documento.paginas)
            await asyncio.to_thread(verificar_saida, Path(dual), documento.paginas * 2)
            if await asyncio.to_thread(hash_arquivo, documento.caminho) != documento.sha256:
                raise PDFInvalido("O arquivo original foi alterado durante a tradução.")
            avisos.extend(coletor.mensagens)
            avisos.append(
                "Tradução automática: confira termos, números, fórmulas e tabelas no PDF bilíngue. "
                "A verificação estrutural não comprova fidelidade semântica ou visual."
            )
            identificador = uuid4().hex
            destino = saida / f"traducao-{identificador[:12]}"
            saida.mkdir(parents=True, exist_ok=True)
            # Diretório temporário no mesmo volume: a publicação final é uma renomeação.
            with TemporaryDirectory(prefix=".publicando-", dir=saida) as publicacao:
                pronto = Path(publicacao) / "pronto"
                pronto.mkdir()
                await asyncio.to_thread(shutil.copyfile, mono, pronto / "traduzido.pdf")
                await asyncio.to_thread(shutil.copyfile, dual, pronto / "bilingue.pdf")
                resultado = Resultado(
                    str(destino / "traduzido.pdf"),
                    str(destino / "bilingue.pdf"),
                    documento.paginas,
                    round(monotonic() - inicio, 2),
                    self.config.modelo,
                    documento.sha256,
                    avisos,
                )
                gravar_json(pronto / "relatorio.json", asdict(resultado))
                pronto.rename(destino)
            yield Evento("Tradução concluída; revisão recomendada", 100, resultado)
