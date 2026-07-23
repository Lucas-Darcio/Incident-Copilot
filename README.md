# Incident Copilot — Multi-Agent Human-in-the-Loop

## O que é este projeto (em termos simples)

Quando um sistema de software (um site, um app, uma API) apresenta um
problema: fica lento, para de responder, ou consome recursos demais;
isso é chamado de **incidente**. Em qualquer empresa que opera software
em produção, existe uma equipe (frequentemente chamada de **SRE** —
*Site Reliability Engineering*, ou simplesmente "time de operações")
responsável por perceber esses problemas rapidamente e corrigi-los
antes que afetem muitos usuários (às vezes literalmente sendo acordada
de madrugada para isso).

O processo tradicional é assim: um alerta automático dispara, uma
pessoa recebe a notificação, ela precisa **investigar** (olhar
métricas, logs, documentação interna de "o que fazer quando X
acontece") e só então decidir e aplicar uma correção. Esse processo de
investigação manual é lento e depende muito da experiência de quem
está de plantão naquele momento.

Este projeto constrói um **copiloto de IA** que automatiza a parte de
*investigação e diagnóstico* desse processo: um sistema de múltiplos
"agentes" de inteligência artificial que recebe o alerta automaticamente,
busca em uma base de conhecimento (documentos internos de como resolver
problemas parecidos) e propõe um diagnóstico e uma ação corretiva,
tudo isso em segundos, ao invés de minutos ou horas de investigação
manual.

**O ponto mais importante do projeto**: o sistema **nunca executa uma
ação corretiva sozinho**. Ele só recomenda e uma pessoa real precisa
revisar e aprovar antes de qualquer mudança de verdade acontecer (isso
se chama **human-in-the-loop**). Isso é essencial
porque IA pode errar, e ações em sistemas de produção (reiniciar um
servidor, por exemplo) podem ter consequências sérias se aplicadas
sem critério.

### Por que isso importa no mercado

Incidentes de produção custam caro, não só em termos de receita
perdida durante o problema, mas também no tempo (e estresse) da equipe
técnica. Uma métrica muito usada na área é o **MTTR** (*Mean Time To
Resolution*, o tempo médio até resolver um incidente); reduzir esse
tempo é uma prioridade constante em empresas de tecnologia. Por isso,
existe um mercado inteiro (geralmente chamado de **AIOps** — *AI for
IT Operations*) de ferramentas que usam IA para acelerar exatamente
essa etapa de diagnóstico. Alguns exemplos de aplicação real:

- **Um e-commerce durante a Black Friday**: o checkout começa a ficar
  lento. Ao invés do time de plantão vasculhar dashboards e logs na
  correria, um copiloto como este já aparece com "causa provável:
  esgotamento de conexões com o banco de dados, ação recomendada:
  aumentar o pool de conexões", e o humano só precisa confirmar.
- **Uma empresa de SaaS com uma API usada por outros sistemas**: quando
  a API fica fora do ar às 3h da manhã, o engenheiro de plantão (que
  acabou de acordar e não tem contexto nenhum do incidente) recebe já
  um diagnóstico inicial baseado nos runbooks da empresa, ao invés de
  começar a investigação do zero.

Esse projeto é uma versão enxuta e de portfólio desse conceito, a
mesma ideia central de ferramentas comerciais desse mercado, construída
para eu aprender e demonstrar as peças técnicas por trás dela:
observabilidade, RAG, sistemas multi-agente e aprovação humana.

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
agent-orchestrator (LangGraph: triagem → retrieval → diagnóstico)
      │  consulta
      ▼
rag-service (busca semântica nos runbooks)

runbooks/*.md
      │  leitura + chunking por seção
      ▼
sentence-transformers (all-MiniLM-L6-v2, local, sem custo de API)
      │  gera embeddings
      ▼
qdrant (vector database)
```

O `agent-orchestrator` (Fase 4) roda um grafo LangGraph com 3 agentes em
sequência:

1. **Triagem**: interpreta o payload bruto do Alertmanager e extrai um
   resumo em texto + a severidade original
2. **Retrieval**: usa esse resumo como query no `rag-service` (Fase 3)
3. **Diagnóstico**: usa um LLM (`gemma-4-31b-it`, via API do Google) para
   sintetizar causa provável + ação recomendada, com base no alerta e
   nos runbooks recuperados

Ainda **sem aprovação humana** nesta fase — o agente só recomenda, não
executa nada. Isso é o foco da Fase 5.

> **Nota sobre custo de LLM**: o Alertmanager reenvia um alerta `firing`
> periodicamente enquanto ele continuar ativo (`repeat_interval`). Sem
> controle, isso chamaria o LLM de novo a cada reenvio do MESMO
> incidente. O `agent-orchestrator` deduplica por `fingerprint` (o
> identificador estável que o Alertmanager gera por incidente), reenvios
> são ignorados sem custo, e o controle é liberado assim que o alerta é
> marcado como `resolved`, garantindo que um incidente futuro do mesmo
> tipo seja tratado como novo.
>
> **Nota sobre timeout do Alertmanager**: o campo `group_interval`
> (configurado em `alertmanager.yml`) também define o tempo máximo que o
> Alertmanager espera pela resposta do webhook antes de desistir
> ("context deadline exceeded" nos logs). Como nosso processamento
> envolve chamadas de rede ao RAG e ao LLM, ele pode ultrapassar esse
> tempo facilmente. Por isso, o `/webhook` responde **imediatamente**
> (aceitando o alerta) e processa o diagnóstico em segundo plano
> (`BackgroundTasks`), o resultado fica disponível para consulta em
> `GET /incidents/{fingerprint}`.

> **Nota de arquitetura (Fase 2)**: optei por rodar o `stress-ng`
> **dentro do próprio container `app-fake`** (via subprocess) ao invés
> de um `chaos-injector` externo, para manter o comportamento
> determinístico e reprodutível em qualquer máquina. Simular um
> "vizinho barulhento" (carga externa disputando os mesmos núcleos
> físicos) fica como exercício avançado futuro.
>
> **Nota técnica importante (Fase 2)**: a métrica `cpu_usage_percent` é
> lida diretamente do **cgroup** do container (o mesmo mecanismo que o
> `docker stats` usa), e expressa como *percentual do limite do próprio
> container*, não como percentual de um núcleo inteiro do host. Isso
> evita um erro comum: usar `psutil.cpu_percent()` puro dentro de um
> container faz a leitura vir de `/proc/stat`, que ainda reflete a
> máquina host inteira, gerando números artificialmente baixos e que
> nunca cruzam o threshold de alerta.

## Configuração (necessária a partir da Fase 4)

O `agent-orchestrator` precisa de uma chave da API do Google (Gemini/Gemma):

```bash
cp .env.example .env
# edite o .env e cole sua chave
```

O `.env` está no `.gitignore`.

## Como rodar

```bash
docker compose up --build
```

> O primeiro build do `rag-service` demora alguns minutos, ele baixa o
> PyTorch (CPU-only) e o modelo de embedding durante a construção da
> imagem, para o container já subir pronto para uso.

Serviços disponíveis:
- `app-fake`: http://localhost:8000 (docs em `/docs`)
- `prometheus`: http://localhost:9090
- `alertmanager`: http://localhost:9093
- `agent-orchestrator`: http://localhost:8001 (docs em `/docs`)
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

5. Confira nos logs do `agent-orchestrator` que o alerta chegou e foi
   processado pelos 3 agentes (triagem, retrieval, diagnóstico):
   ```bash
   docker compose logs -f agent-orchestrator
   ```
   Você deve ver algo como:
   ```
   [agent-orchestrator] thread_id=...
     alerta: HighCPUUsage: CPU alta detectada em app-fake:8000. ...
     diagnóstico: ...
     ação recomendada: ...
     severidade avaliada: ...
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
   literalmente na pergunta, isso é a busca semântica funcionando
   (compara *significado*, não só palavras-chave).

3. Explore a coleção diretamente pelo painel do Qdrant:
   http://localhost:6333/dashboard

## Como testar — Agentes (Fase 4)

### Teste manual rápido (síncrono, sem depender do Alertmanager)

```bash
curl -X POST http://localhost:8001/diagnose \
  -H "Content-Type: application/json" \
  -d '{
    "alertname": "HighCPUUsage",
    "summary": "CPU alta detectada em app-fake:8000",
    "description": "cpu_usage_percent está em 97% (limite: 80%) há mais de 15s",
    "severity": "critical"
  }'
```

A resposta já traz `diagnosis`, `recommended_action` e
`severity_assessed` na hora, esse endpoint (`/diagnose`) roda o grafo
de forma síncrona e existe só para facilitar testes manuais durante o
desenvolvimento.

### Fluxo real (assíncrono, via Alertmanager)

O endpoint que o Alertmanager efetivamente chama é o `/webhook`, que
responde imediatamente e processa em segundo plano (ver nota acima
sobre timeout). Rode o incidente de verdade:

```bash
curl -X POST http://localhost:8000/chaos/start
docker compose logs -f agent-orchestrator
```

Depois de alguns segundos, consulte o resultado:

```bash
curl http://localhost:8001/incidents        # lista todos os diagnósticos já concluídos
```

Compare o `diagnosis` retornado com o conteúdo de
`runbooks/runbook-high-cpu.md` para conferir se o raciocínio do agente
faz sentido.

## Roadmap

- [x] Fase 0 — Setup do repositório
- [x] Fase 1 — Ambiente alvo + observabilidade (Prometheus/Alertmanager)
- [x] Fase 2 — Chaos injection real com `stress-ng`
- [x] Fase 3 — Base de conhecimento RAG (runbooks + embeddings locais + Qdrant)
- [x] Fase 4 — Agentes multi-agente com LangGraph (triagem, retrieval, diagnóstico)
- [ ] Fase 5 — Human-in-the-loop (aprovação de ações corretivas)
- [ ] Fase 6 — Dashboard
- [ ] Fase 7 — Polimento e documentação final

## Arquitetura (visão de produto final)

O `agent-orchestrator` (Fase 4) terá acesso ao socket do Docker do host
para executar ações corretivas aprovadas por um humano (ex: restart de
container). Ver seção "Ações corretivas" assim que a Fase 5 for
implementada.
