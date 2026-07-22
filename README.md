# Incident Copilot — Multi-Agent Human-in-the-Loop

Copiloto de resposta a incidentes usando sistemas multi-agente (LangGraph)
com aprovação humana obrigatória antes de qualquer ação corretiva real.

## Arquitetura geral

```
app-fake (mede CPU real via cgroup + roda stress-ng sob demanda)
      │  scrape a cada 5s
      ▼
prometheus (avalia regras)
      │  se cpu_usage_percent > 80% por 15s
      ▼
alertmanager (agrupa e envia)
      │  webhook HTTP POST
      ▼
webhook-receiver (temporário — vira o agent-orchestrator na Fase 4)

runbooks/*.md
      │  leitura + chunking por seção
      ▼
sentence-transformers (all-MiniLM-L6-v2, local, sem custo de API)
      │  gera embeddings
      ▼
qdrant (vector database)
      │  busca por similaridade
      ▼
rag-service: POST /search → runbooks mais relevantes para uma consulta
```

O `rag-service` funciona isolado de propósito nesta fase — ele não
depende de agentes. A conexão com o multi-agente (LangGraph) só
acontece na Fase 4, quando o agente de diagnóstico vai *consumir* esse
mesmo endpoint `/search`.

> **Nota de arquitetura (Fase 2)**: optamos por rodar o `stress-ng`
> **dentro do próprio container `app-fake`** (via subprocess) ao invés
> de um `chaos-injector` externo, para manter o comportamento
> determinístico e reprodutível em qualquer máquina. Simular um
> "vizinho barulhento" (carga externa disputando os mesmos núcleos
> físicos) fica como exercício avançado futuro.
>
> **Nota técnica importante (Fase 2)**: a métrica `cpu_usage_percent` é
> lida diretamente do **cgroup** do container (o mesmo mecanismo que o
> `docker stats` usa), e expressa como *percentual do limite do próprio
> container* — não como percentual de um núcleo inteiro do host. Isso
> evita um erro comum: usar `psutil.cpu_percent()` puro dentro de um
> container faz a leitura vir de `/proc/stat`, que ainda reflete a
> máquina host inteira, gerando números artificialmente baixos e que
> nunca cruzam o threshold de alerta.

## Como rodar

```bash
docker compose up --build
```

> O primeiro build do `rag-service` demora alguns minutos — ele baixa o
> PyTorch (CPU-only) e o modelo de embedding durante a construção da
> imagem, para o container já subir pronto para uso.

Serviços disponíveis:
- `app-fake`: http://localhost:8000 (docs em `/docs`)
- `prometheus`: http://localhost:9090
- `alertmanager`: http://localhost:9093
- `webhook-receiver`: http://localhost:8001
- `rag-service`: http://localhost:8002 (docs em `/docs`)
- `qdrant`: http://localhost:6333/dashboard

## Como testar — pipeline de incidentes (Fases 1 e 2)

1. Confirme que tudo subiu:
   ```bash
   curl http://localhost:8000/health
   ```

2. Dispare o incidente real (stress-ng ocupando 1 núcleo por até 120s):
   ```bash
   curl -X POST http://localhost:8000/chaos/start
   ```

3. Acompanhe a métrica subindo em tempo real:
   http://localhost:9090/graph → busque por `cpu_usage_percent`

   Dica: rode `docker stats app-fake` em outro terminal para comparar
   com o consumo real de CPU/memória do container.

4. Depois de ~15-20s, veja o alerta ativo no Prometheus:
   http://localhost:9090/alerts

5. Confira nos logs do `webhook-receiver` que o alerta chegou:
   ```bash
   docker compose logs -f webhook-receiver
   ```

6. Pare o incidente manualmente (ou espere os 120s do timeout de
   segurança) e veja o alerta ser resolvido:
   ```bash
   curl -X POST http://localhost:8000/chaos/stop
   ```

## Como testar — RAG (Fase 3)

1. Popule o Qdrant com os runbooks:
   ```bash
   curl -X POST http://localhost:8002/ingest
   ```
   Deve retornar algo como `{"chunks_indexados": 20}`.

2. Teste uma busca semântica:
   ```bash
   curl -X POST http://localhost:8002/search \
     -H "Content-Type: application/json" \
     -d '{"query": "container consumindo muito processamento", "top_k": 3}'
   ```
   O resultado esperado é o runbook de CPU alta aparecer em primeiro
   lugar (maior `score`), mesmo sem a palavra "CPU" aparecer
   literalmente na pergunta — isso é a busca semântica funcionando
   (compara *significado*, não só palavras-chave).

3. Explore a coleção diretamente pelo painel do Qdrant:
   http://localhost:6333/dashboard

## Roadmap

- [x] Fase 0 — Setup do repositório
- [x] Fase 1 — Ambiente alvo + observabilidade (Prometheus/Alertmanager)
- [x] Fase 2 — Chaos injection real com `stress-ng`
- [x] Fase 3 — Base de conhecimento RAG (runbooks + embeddings locais + Qdrant)
- [ ] Fase 4 — Agentes multi-agente com LangGraph
- [ ] Fase 5 — Human-in-the-loop (aprovação de ações corretivas)
- [ ] Fase 6 — Dashboard
- [ ] Fase 7 — Polimento e documentação final

## Arquitetura (visão de produto final)

O `agent-orchestrator` (Fase 4) terá acesso ao socket do Docker do host
para executar ações corretivas aprovadas por um humano (ex: restart de
container). Ver seção "Ações corretivas" assim que a Fase 5 for
implementada.
