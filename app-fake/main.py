"""
App fake que simula um serviço monitorado.
Expõe métricas no padrão Prometheus e um endpoint para simular
uma condição de "incidente" (CPU alta) sem precisar de stress-ng ainda.
Isso é suficiente para validar todo o pipeline de alertas na Fase 1.
"""
import random
import threading
import time

from fastapi import FastAPI
from prometheus_client import Gauge, Counter, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

app = FastAPI(title="app-fake")

# --- Métricas ---
# Gauge: valor que sobe e desce (ex: uso de CPU, memória)
cpu_usage_percent = Gauge(
    "cpu_usage_percent", "Uso de CPU simulado do serviço (%)"
)
# Counter: valor que só cresce (ex: total de requisições)
http_requests_total = Counter(
    "http_requests_total", "Total de requisições recebidas", ["endpoint", "status"]
)

# Estado interno: se está em modo "incidente" ou normal
_state = {"chaos": False}


def _cpu_loop():
    """
    Thread de background que atualiza a métrica de CPU continuamente.
    Em modo normal, oscila entre 5-20%. Em modo chaos, oscila entre 85-99%.
    O Prometheus vai "puxar" (scrape) esse valor periodicamente.
    """
    while True:
        if _state["chaos"]:
            cpu_usage_percent.set(random.uniform(85, 99))
        else:
            cpu_usage_percent.set(random.uniform(5, 20))
        time.sleep(2)


threading.Thread(target=_cpu_loop, daemon=True).start()


@app.get("/")
def root():
    http_requests_total.labels(endpoint="/", status="200").inc()
    return {"service": "app-fake", "status": "ok", "chaos_mode": _state["chaos"]}


@app.get("/health")
def health():
    http_requests_total.labels(endpoint="/health", status="200").inc()
    return {"status": "healthy" if not _state["chaos"] else "degraded"}


@app.post("/chaos/start")
def start_chaos():
    """Simula início de um incidente (CPU alta)."""
    _state["chaos"] = True
    return {"chaos_mode": True, "message": "Simulando CPU alta"}


@app.post("/chaos/stop")
def stop_chaos():
    """Simula resolução do incidente (ex: efeito de um restart)."""
    _state["chaos"] = False
    return {"chaos_mode": False, "message": "Voltando ao normal"}


@app.get("/metrics")
def metrics():
    """Endpoint que o Prometheus faz scraping. Formato texto padrão Prometheus."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)