import json
import time
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from test_servico import ModeloSimulado, MotorSimulado
from tradutor.servico import ServicoTraducao
from tradutor.tarefas import GerenciadorTarefas, Tarefa
from tradutor.web import criar_app


def test_upload_consulta_download(pdf, config):
    servico = ServicoTraducao(config, ModeloSimulado(), MotorSimulado())
    with TestClient(criar_app(config, servico)) as client:
        assert client.get("/").status_code == 200
        assert client.get("/saude").json()["modelo"] == "pronto"
        response = client.post("/api/traducoes", files={"arquivo": ("artigo.pdf", pdf.read_bytes())})
        assert response.status_code == 202
        url = "/api/traducoes/" + response.json()["id"]
        for _ in range(100):
            tarefa = client.get(url).json()
            if tarefa["estado"] not in {"aguardando", "processando"}:
                break
            time.sleep(0.02)
        assert tarefa["estado"] == "concluida", tarefa
        for tipo in ["traduzido", "bilingue"]:
            response = client.get(url + "/arquivos/" + tipo)
            assert response.status_code == 200
            assert response.content.startswith(b"%PDF")
        assert client.get(url + "/arquivos/outro").status_code == 422


def test_upload_falso_rejeitado(config):
    with TestClient(criar_app(config)) as client:
        response = client.post("/api/traducoes", files={"arquivo": ("falso.pdf", b"not pdf")})
        assert response.status_code == 400
        assert not list((config.dados / "entradas").glob("*.pdf"))


def test_estado_nao_concluido_bloqueia_download(config):
    servico = ServicoTraducao(config, ModeloSimulado(), MotorSimulado())
    app = criar_app(config, servico)
    id_tarefa = str(uuid4())
    with TestClient(app) as client:
        app.state.gerente.tarefas[id_tarefa] = Tarefa(id=id_tarefa, nome="artigo.pdf")
        assert client.get(f"/api/traducoes/{id_tarefa}/arquivos/traduzido").status_code == 409
        assert client.get("/api/traducoes/inexistente").status_code == 404


def test_reinicio_marca_interrompida(config):
    servico = ServicoTraducao(config, ModeloSimulado(), MotorSimulado())
    gerente = GerenciadorTarefas(servico)
    tarefa = Tarefa(id=str(uuid4()), nome="artigo.pdf", estado="processando")
    gerente.salvar(tarefa)
    gerente.restaurar()
    assert gerente.buscar(tarefa.id).estado == "interrompida"
    dados = json.loads((gerente.pasta / f"{tarefa.id}.json").read_text())
    assert dados["estado"] == "interrompida"


def test_download_nao_pode_sair_da_pasta_da_tarefa(config, tmp_path):
    app = criar_app(config)
    id_tarefa = str(uuid4())
    secreto = tmp_path / "outro.pdf"
    secreto.write_bytes(b"conteudo fora dos resultados")
    with TestClient(app) as client:
        app.state.gerente.tarefas[id_tarefa] = Tarefa(
            id=id_tarefa, nome="artigo.pdf", estado="concluida",
            resultado={"traduzido": str(secreto)},
        )
        assert client.get(f"/api/traducoes/{id_tarefa}/arquivos/traduzido").status_code == 404


def test_cancelamento_e_concorrencia_web(pdf, config):
    motor = MotorSimulado("esperar")
    app = criar_app(config, ServicoTraducao(config, ModeloSimulado(), motor))
    with TestClient(app) as client:
        body = {"arquivo": ("artigo.pdf", pdf.read_bytes())}
        first = client.post("/api/traducoes", files=body).json()
        assert client.post("/api/traducoes", files=body).status_code == 409
        response = client.post(f"/api/traducoes/{first['id']}/cancelar")
        assert response.json()["estado"] == "cancelada"


def test_nome_upload_nao_define_caminho(pdf, config):
    app = criar_app(config, ServicoTraducao(config, ModeloSimulado(), MotorSimulado()))
    with TestClient(app) as client:
        response = client.post(
            "/api/traducoes", files={"arquivo": ("../../fora.pdf", pdf.read_bytes())}
        )
        assert response.status_code == 202
        assert response.json()["nome"] == "fora.pdf"
    assert not Path(config.dados.parent / "fora.pdf").exists()
