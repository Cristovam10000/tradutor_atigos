class ErroTraducao(Exception):
    """Falha conhecida que pode ser apresentada ao usuário."""

    codigo = "traducao_falhou"


class PDFInvalido(ErroTraducao):
    codigo = "pdf_invalido"


class PDFProtegido(PDFInvalido):
    codigo = "pdf_protegido"


class PDFDigitalizado(PDFInvalido):
    codigo = "pdf_digitalizado"


class ModeloIndisponivel(ErroTraducao):
    codigo = "modelo_indisponivel"


class RespostaInvalida(ErroTraducao):
    codigo = "resposta_invalida"


class Ocupado(ErroTraducao):
    codigo = "ocupado"


class TempoExcedido(ErroTraducao):
    codigo = "tempo_excedido"
