from dataclasses import replace

import pymupdf
import pytest

from tradutor.erros import PDFDigitalizado, PDFInvalido, PDFProtegido
from tradutor.pdf import inspecionar_pdf, verificar_saida


def test_pdf_valido_tem_hash_e_contagem(pdf, config):
    resultado = inspecionar_pdf(pdf, config)
    assert resultado.paginas == 1
    assert len(resultado.sha256) == 64
    assert resultado.avisos == ()


def test_extensao_nao_substitui_validacao_conteudo(tmp_path, config):
    arquivo = tmp_path / "falso.pdf"
    arquivo.write_text("Isto não é um PDF.", encoding="utf-8")
    with pytest.raises(PDFInvalido, match="conteúdo"):
        inspecionar_pdf(arquivo, config)


def test_pdf_truncado(tmp_path, config):
    arquivo = tmp_path / "truncado.pdf"
    arquivo.write_bytes(b"%PDF-1.7\nnot a valid document")
    with pytest.raises(PDFInvalido):
        inspecionar_pdf(arquivo, config)


def test_pdf_protegido(pdf, tmp_path, config):
    protegido = tmp_path / "protegido.pdf"
    with pymupdf.open(pdf) as doc:
        doc.save(protegido, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="exemplo-teste")
    with pytest.raises(PDFProtegido):
        inspecionar_pdf(protegido, config)


def test_pdf_so_imagem_nao_vira_sucesso(pdf, tmp_path, config):
    digitalizado = tmp_path / "digitalizado.pdf"
    with pymupdf.open(pdf) as source, pymupdf.open() as doc:
        pix = source[0].get_pixmap()
        page = doc.new_page()
        page.insert_image(page.rect, pixmap=pix)
        doc.save(digitalizado)
    with pytest.raises(PDFDigitalizado):
        inspecionar_pdf(digitalizado, config)


def test_documento_misto_emite_aviso(pdf, tmp_path, config):
    misto = tmp_path / "misto.pdf"
    with pymupdf.open(pdf) as doc:
        doc.new_page()
        doc.save(misto)
    assert "[2]" in inspecionar_pdf(misto, config).avisos[0]


def test_limite_bytes(pdf, config):
    with pytest.raises(PDFInvalido, match="limite"):
        inspecionar_pdf(pdf, replace(config, max_bytes=5))


def test_contagem_saida_errada(pdf):
    with pytest.raises(PDFInvalido, match="quantidade"):
        verificar_saida(pdf, 2)
