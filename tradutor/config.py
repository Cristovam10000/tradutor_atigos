"""Configuração explícita; nenhum provedor de tradução na nuvem."""

import ipaddress
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class Config:
    dados: Path = Path("dados")
    ollama_host: str = "http://localhost:11434"
    modelo: str = "artigos-hymt2:q8"
    contexto: int = 8192
    max_saida_tokens: int = 4096
    timeout_modelo: float = 300
    timeout_tarefa: float = 3600
    max_bytes: int = 50 * 1024 * 1024
    max_paginas: int = 200

    def __post_init__(self) -> None:
        url = urlparse(self.ollama_host)
        nomes_locais = {"localhost", "modelo", "host.docker.internal", "testserver"}
        local = url.hostname in nomes_locais
        if not local and url.hostname:
            try:
                local = ipaddress.ip_address(url.hostname).is_private
            except ValueError:
                local = False
        if not local or url.scheme != "http" or url.username or url.password:
            raise ValueError(
                "OLLAMA_HOST deve apontar para um servidor HTTP local, sem credenciais."
            )
        if self.contexto != 8192:
            raise ValueError("Esta versão foi configurada para contexto de 8192 tokens.")
        if min(self.max_bytes, self.max_paginas, self.timeout_modelo, self.timeout_tarefa) <= 0:
            raise ValueError("Os limites de tamanho, páginas e tempo devem ser positivos.")
        object.__setattr__(self, "dados", self.dados.resolve())
        object.__setattr__(self, "ollama_host", self.ollama_host.rstrip("/"))

    @classmethod
    def ambiente(cls) -> "Config":
        return cls(
            dados=Path(os.getenv("TRADUTOR_DADOS", "dados")),
            ollama_host=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
            modelo=os.getenv("TRADUTOR_MODELO", "artigos-hymt2:q8"),
            timeout_modelo=float(os.getenv("TRADUTOR_TIMEOUT_MODELO", "300")),
            timeout_tarefa=float(os.getenv("TRADUTOR_TIMEOUT_TAREFA", "3600")),
        )
