"""Inspeção do documento original e validação estrutural dos resultados."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from tradutor.config import Config
from tradutor.erros import PDFDigitalizado, PDFInvalido, PDFProtegido


@dataclass(frozen=True)
class Documento:
    caminho: Path
    paginas: int
    sha256: str
    avisos: tuple[str, ...]


def hash_arquivo(caminho: Path) -> str:
    with caminho.open("rb") as arquivo:
        return hashlib.file_digest(arquivo, "sha256").hexdigest()


def inspecionar_pdf(caminho: Path, config: Config) -> Documento:
    caminho = caminho.resolve()
    if not caminho.is_file():
        raise PDFInvalido("O arquivo informado não existe.")
    if caminho.suffix.lower() != ".pdf":
        raise PDFInvalido("Selecione um arquivo com extensão .pdf.")
    if caminho.stat().st_size > config.max_bytes:
        raise PDFInvalido("O limite por arquivo é de 50 MB.")
    with caminho.open("rb") as arquivo:
        if b"%PDF-" not in arquivo.read(1024):
            raise PDFInvalido("O conteúdo do arquivo não é um PDF reconhecível.")
    try:
        with pymupdf.open(caminho) as doc:
            if doc.needs_pass:
                raise PDFProtegido("O PDF exige senha. Use uma cópia que possa abrir sem senha.")
            if not doc.permissions & pymupdf.PDF_PERM_COPY:
                raise PDFProtegido("O PDF possui restrição de cópia do texto.")
            if not 1 <= len(doc) <= config.max_paginas:
                raise PDFInvalido(f"O documento deve conter entre 1 e {config.max_paginas} páginas.")
            sem_texto = []
            letras = 0
            for numero, pagina in enumerate(doc, 1):
                texto = pagina.get_text()
                quantidade = sum(char.isalpha() for char in texto)
                letras += quantidade
                if quantidade < 10:
                    sem_texto.append(numero)
            if letras < 30:
                raise PDFDigitalizado(
                    "Não foi encontrado texto selecionável suficiente. "
                    "Esta versão atende PDFs digitais, e não páginas digitalizadas."
                )
            avisos = []
            if sem_texto:
                avisos.append(
                    f"Páginas com pouco ou nenhum texto selecionável: {sem_texto}. "
                    "Texto dentro de imagens permanece no idioma original."
                )
            return Documento(caminho, len(doc), hash_arquivo(caminho), tuple(avisos))
    except (pymupdf.FileDataError, RuntimeError) as exc:
        raise PDFInvalido("Não foi possível ler a estrutura do PDF.") from exc


def verificar_saida(caminho: Path, paginas_esperadas: int) -> None:
    if not caminho.is_file() or caminho.stat().st_size == 0:
        raise PDFInvalido("O motor não produziu o arquivo PDF esperado.")
    try:
        with pymupdf.open(caminho) as doc:
            if doc.needs_pass or len(doc) != paginas_esperadas:
                raise PDFInvalido("O PDF de saída está protegido ou tem quantidade incorreta de páginas.")
            if not any(page.get_text().strip() for page in doc):
                raise PDFInvalido("O PDF de saída não contém texto legível.")
    except (pymupdf.FileDataError, RuntimeError) as exc:
        raise PDFInvalido("O arquivo PDF gerado está corrompido.") from exc
