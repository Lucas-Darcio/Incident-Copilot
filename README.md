# Incident Copilot — Multi-Agent Human-in-the-Loop

Copiloto de resposta a incidentes usando sistemas multi-agente (LangGraph)
com aprovação humana obrigatória antes de qualquer ação corretiva real.

## Status: Fase 1 — Ambiente + Observabilidade

Nesta fase, o objetivo é validar o pipeline completo de detecção de incidentes,
**sem agentes de IA ainda**:

```
app-fake (expõe métricas)
      │  scrape a cada 5s
      ▼
prometheus (avalia regras)
      │  se cpu_usage_percent > 80% por 15s
      ▼
alertmanager (agrupa e envia)
      │  webhook HTTP POST
      ▼
webhook-receiver (temporário — vira o agent-orchestrator na Fase 4)
```

## Como rodar

```bash
docker compose up --build
```

Serviços disponíveis:

- `app-fake`: http://localhost:8000 (docs em `/docs`)
- `prometheus`: http://localhost:9090
- `alertmanager`: http://localhost:9093
- `webhook-receiver`: http://localhost:8001

## Como testar o fluxo de ponta a ponta

1. Confirme que tudo subiu:

   ```bash
   curl http://localhost:8000/health
   ```

2. Dispare o "incidente" simulado (CPU alta):

   ```bash
   curl -X POST http://localhost:8000/chaos/start
   ```

3. Acompanhe a métrica subindo em tempo real:
   http://localhost:9090/graph → busque por `cpu_usage_percent`

4. Depois de ~15-20s, veja o alerta ativo no Prometheus:
   http://localhost:9090/alerts

5. Confira nos logs do `webhook-receiver` que o alerta chegou:

   ```bash
   docker compose logs -f webhook-receiver
   ```

6. Pare o incidente e veja o alerta ser resolvido:
   ```bash
   curl -X POST http://localhost:8000/chaos/stop
   ```

## Roadmap

- [x] Fase 0 — Setup do repositório
- [x] Fase 1 — Ambiente alvo + observabilidade (Prometheus/Alertmanager)
- [ ] Fase 2 — Chaos injection real com `stress-ng`
- [ ] Fase 3 — Base de conhecimento RAG (runbooks)
- [ ] Fase 4 — Agentes multi-agente com LangGraph
- [ ] Fase 5 — Human-in-the-loop (aprovação de ações corretivas)
- [ ] Fase 6 — Dashboard
- [ ] Fase 7 — Polimento e documentação final

## Arquitetura (visão de produto final)

O `agent-orchestrator` (Fase 4) terá acesso ao socket do Docker do host
para executar ações corretivas aprovadas por um humano (ex: restart de
container). Ver seção "Ações corretivas" abaixo assim que a Fase 5 for
implementada.
