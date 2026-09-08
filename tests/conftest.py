from pathlib import Path

import pymupdf
import pytest

from tradutor.config import Config


def criar_pdf(caminho: Path, paginas: int = 1, texto: str | None = None) -> Path:
    with pymupdf.open() as doc:
        for _ in range(paginas):
            page = doc.new_page()
            page.insert_text(
                (50, 70),
                texto or "Software engineering uses evidence to validate a system and its requirements.",
            )
        doc.save(caminho)
    return caminho


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(dados=tmp_path / "dados", ollama_host="http://modelo:11434")


@pytest.fixture
def pdf(tmp_path: Path) -> Path:
    return criar_pdf(tmp_path / "artigo.pdf")
