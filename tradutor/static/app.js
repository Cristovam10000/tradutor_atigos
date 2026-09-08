const $ = (id) => document.getElementById(id);
const fileInput = $("arquivo");
let currentId = null;
let pollTimer = null;

function showError(message) {
  $("erro").textContent = message;
  $("erro").hidden = false;
}
function showFile() {
  const file = fileInput.files[0];
  $("nome-arquivo").textContent = file ? file.name : "Escolha seu artigo";
  $("detalhe-arquivo").textContent = file
    ? `${(file.size / 1024 / 1024).toFixed(2)} MB · Pronto para traduzir`
    : "Arraste um PDF ou clique para selecionar";
}
async function api(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Não foi possível processar a solicitação.");
  return data;
}
function renderJob(job) {
  $("andamento").hidden = false;
  $("etapa").textContent = job.etapa;
  $("progresso").value = job.progresso;
  $("percentual").textContent = `${Math.round(job.progresso)}%`;
  const running = ["aguardando", "processando"].includes(job.estado);
  $("traduzir").disabled = running;
  fileInput.disabled = running;
  $("cancelar").hidden = !running;
  if (job.estado === "concluida") {
    $("resultado").hidden = false;
    $("baixar-traduzido").href = `/api/traducoes/${job.id}/arquivos/traduzido`;
    $("baixar-bilingue").href = `/api/traducoes/${job.id}/arquivos/bilingue`;
    $("metricas").textContent = `${job.resultado.paginas} página(s) · ${job.resultado.segundos}s de processamento`;
    $("avisos").replaceChildren(...job.resultado.avisos.map((text) => {
      const item = document.createElement("li"); item.textContent = text; return item;
    }));
  } else if (["falhou", "interrompida"].includes(job.estado)) {
    showError(job.erro || job.etapa);
  }
  if (running) pollTimer = setTimeout(poll, 1200);
}
async function poll() {
  try { renderJob(await api(`/api/traducoes/${currentId}`)); }
  catch (error) {
    showError(`Não foi possível consultar o andamento: ${error.message} Nova tentativa em 5 segundos.`);
    pollTimer = setTimeout(poll, 5000);
  }
}
fileInput.addEventListener("change", showFile);
for (const event of ["dragenter", "dragover"]) $("area-arquivo").addEventListener(event, (e) => {
  e.preventDefault(); $("area-arquivo").classList.add("drag");
});
for (const event of ["dragleave", "drop"]) $("area-arquivo").addEventListener(event, (e) => {
  e.preventDefault(); $("area-arquivo").classList.remove("drag");
});
$("area-arquivo").addEventListener("drop", (event) => {
  if (fileInput.disabled || event.dataTransfer.files.length !== 1) return;
  fileInput.files = event.dataTransfer.files; showFile();
});
$("formulario").addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = fileInput.files[0];
  if (!file || !file.name.toLowerCase().endsWith(".pdf")) return showError("Selecione um PDF.");
  if (file.size > 50 * 1024 * 1024) return showError("O limite por arquivo é de 50 MB.");
  clearTimeout(pollTimer);
  $("erro").hidden = true; $("resultado").hidden = true; $("traduzir").disabled = true;
  const body = new FormData(); body.append("arquivo", file);
  try {
    const job = await api("/api/traducoes", { method: "POST", body });
    currentId = job.id; localStorage.setItem("margem-tarefa", currentId); renderJob(job);
  } catch (error) { showError(error.message); $("traduzir").disabled = false; }
});
$("cancelar").addEventListener("click", async () => {
  clearTimeout(pollTimer); $("cancelar").disabled = true;
  try { renderJob(await api(`/api/traducoes/${currentId}/cancelar`, {method:"POST"})); }
  catch (error) { showError(error.message); pollTimer = setTimeout(poll, 1200); }
  finally { $("cancelar").disabled = false; }
});
async function initialize() {
  try {
    const health = await api("/saude");
    $("estado-modelo").textContent = health.modelo === "pronto" ? "● Tradutor local pronto" : health.mensagem;
  } catch { $("estado-modelo").textContent = "Não foi possível conectar ao tradutor local."; }
  const saved = localStorage.getItem("margem-tarefa");
  if (saved) {
    try { const job = await api(`/api/traducoes/${saved}`); currentId = saved; renderJob(job); }
    catch { localStorage.removeItem("margem-tarefa"); }
  }
}
initialize();
