"""
App fake que simula um serviço monitorado.

A métrica de CPU agora é lida diretamente do cgroup do container (o 
mesmo mecanismo que o `docker stats` usa), e expressa como percentual 
RELATIVO AO PRÓPRIO LIMITE do container (definido no docker-compose.yml).
Isso é o que ferramentas reais de observabilidade (cAdvisor, Kubernetes) 
fazem: "quanto da capacidade alocada está sendo usada", que é a pergunta 
certa para decidir se algo está sobrecarregado.
"""
import os
import subprocess
import threading
import time

import psutil
from fastapi import FastAPI
from prometheus_client import Gauge, Counter, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

app = FastAPI(title="app-fake")

cpu_usage_percent = Gauge(
    "cpu_usage_percent",
    "Uso de CPU do container, relativo ao seu próprio limite (0-100+ %)",
)
http_requests_total = Counter(
    "http_requests_total", "Total de requisições recebidas", ["endpoint", "status"]
)

_state = {"chaos_process": None}


# ##### Leitura de CPU via cgroup
# Por que não usamos psutil.cpu_percent() direto: dentro de um container,
# /proc/stat ainda reflete a máquina HOST inteira, não o que foi alocado
# para este container. Isso faz o valor parecer artificialmente baixo.
# Lemos o cgroup diretamente, que é a mesma fonte que o `docker stats` usa.

_CGROUP_V2_MAX = "/sys/fs/cgroup/cpu.max"
_CGROUP_V2_STAT = "/sys/fs/cgroup/cpu.stat"
_CGROUP_V1_QUOTA = "/sys/fs/cgroup/cpu/cpu.cfs_quota_us"
_CGROUP_V1_PERIOD = "/sys/fs/cgroup/cpu/cpu.cfs_period_us"
_CGROUP_V1_USAGE = "/sys/fs/cgroup/cpuacct/cpuacct.usage"


def _detect_cgroup_mode():
    if os.path.exists(_CGROUP_V2_MAX) and os.path.exists(_CGROUP_V2_STAT):
        return "v2"
    if os.path.exists(_CGROUP_V1_QUOTA) and os.path.exists(_CGROUP_V1_USAGE):
        return "v1"
    return "fallback"


def _read_quota_cores(mode):
    """Quantos núcleos (podendo ser fracionário, ex: 0.5) este container
    pode usar no máximo. Retorna None se não houver limite configurado."""
    try:
        if mode == "v2":
            quota_str, period_str = open(_CGROUP_V2_MAX).read().split()
            if quota_str == "max":
                return None
            return int(quota_str) / int(period_str)
        if mode == "v1":
            quota = int(open(_CGROUP_V1_QUOTA).read().strip())
            period = int(open(_CGROUP_V1_PERIOD).read().strip())
            if quota == -1:
                return None
            return quota / period
    except (FileNotFoundError, ValueError):
        return None
    return None


def _read_usage_seconds(mode):
    """Tempo total de CPU (em segundos) já consumido pelo container desde
    que ele iniciou. Valor cumulativo — por isso medimos em intervalos."""
    if mode == "v2":
        for line in open(_CGROUP_V2_STAT):
            if line.startswith("usage_usec"):
                return int(line.split()[1]) / 1_000_000
    if mode == "v1":
        return int(open(_CGROUP_V1_USAGE).read().strip()) / 1_000_000_000
    return None


_cgroup_mode = _detect_cgroup_mode()
_quota_cores = _read_quota_cores(_cgroup_mode) if _cgroup_mode != "fallback" else None
print(f"[app-fake] modo de leitura de CPU: {_cgroup_mode}, limite detectado: {_quota_cores}")


def _cpu_loop():
    """
    A cada 2s, calcula quantos núcleos foram consumidos NESSE intervalo
    (delta de uso / delta de tempo) e expressa isso como percentual do
    limite do próprio container. Ex: se o limite é 0.5 núcleo e o
    container usou 0.5 núcleo nesse intervalo, o resultado é 100%.
    """
    if _cgroup_mode == "fallback" or _quota_cores is None:
        # Sem cgroup legível ou sem limite definido: cai para psutil,
        # normalizado pelo número de núcleos do host (menos preciso,
        # mas evita quebrar em ambientes sem suporte a cgroup).
        psutil.cpu_percent(interval=None)
        while True:
            time.sleep(2)
            cores_total = psutil.cpu_count() or 1
            cpu_usage_percent.set(psutil.cpu_percent(interval=None) * cores_total / 100)
        return

    last_usage = _read_usage_seconds(_cgroup_mode)
    last_time = time.monotonic()
    while True:
        time.sleep(2)
        usage = _read_usage_seconds(_cgroup_mode)
        now = time.monotonic()
        cores_used = (usage - last_usage) / (now - last_time)
        percent_of_limit = (cores_used / _quota_cores) * 100
        cpu_usage_percent.set(percent_of_limit)
        last_usage, last_time = usage, now


threading.Thread(target=_cpu_loop, daemon=True).start()


def _chaos_ativo():
    """
    Verifica se o stress-ng ainda está rodando de verdade.
    """
    processo = _state["chaos_process"]
    if processo is None:
        return False
    if processo.poll() is not None:
        _state["chaos_process"] = None
        return False
    return True


@app.get("/")
def root():
    http_requests_total.labels(endpoint="/", status="200").inc()
    return {"service": "app-fake", "status": "ok", "chaos_mode": _chaos_ativo()}


@app.get("/health")
def health():
    http_requests_total.labels(endpoint="/health", status="200").inc()
    return {"status": "degraded" if _chaos_ativo() else "healthy"}


@app.post("/chaos/start")
def start_chaos():
    if _chaos_ativo():
        return {"chaos_mode": True, "message": "Já estava em modo chaos"}

    processo = subprocess.Popen(["stress-ng", "--cpu", "1", "--timeout", "120s"])
    _state["chaos_process"] = processo
    return {"chaos_mode": True, "message": "stress-ng iniciado (auto-encerra em 120s)"}


@app.post("/chaos/stop")
def stop_chaos():
    if not _chaos_ativo():
        return {"chaos_mode": False, "message": "Não havia chaos ativo"}

    processo = _state["chaos_process"]
    processo.terminate()
    processo.wait(timeout=5)
    _state["chaos_process"] = None
    return {"chaos_mode": False, "message": "stress-ng encerrado"}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
