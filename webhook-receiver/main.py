"""
Receiver temporário só para a Fase 1: recebe o webhook do Alertmanager
e imprime no console/log, para você validar visualmente que o alerta
chegou. Na Fase 4 este serviço vira o agent-orchestrator (LangGraph).
"""
from datetime import datetime

from fastapi import FastAPI, Request

app = FastAPI(title="webhook-receiver (temporário)")


@app.post("/webhook")
async def receive_alert(request: Request):
    payload = await request.json()
    print("=" * 60)
    print(f"[{datetime.utcnow().isoformat()}] Alerta recebido:")
    for alert in payload.get("alerts", []):
        print(f"  status: {alert.get('status')}")
        print(f"  alertname: {alert.get('labels', {}).get('alertname')}")
        print(f"  instance: {alert.get('labels', {}).get('instance')}")
        print(f"  summary: {alert.get('annotations', {}).get('summary')}")
    print("=" * 60)
    return {"received": True}


@app.get("/health")
def health():
    return {"status": "ok"}
