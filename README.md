# 🚨 Incident Copilot

**Copiloto de resposta a incidentes com sistema multi-agente (LangGraph), RAG e aprovação humana obrigatória antes de qualquer ação corretiva real.**

Projeto de portfólio construído para aplicar, na prática, observabilidade, RAG, sistemas multi-agente e human-in-the-loop — com Python, Docker, LangGraph, LangChain e Postgres.

---

## Sumário

- [O que é este projeto](#o-que-é-este-projeto)
- [Por que isso importa no mercado](#por-que-isso-importa-no-mercado)
- [Arquitetura](#arquitetura)
- [Stack técnica](#stack-técnica)
- [Como rodar](#como-rodar)
- [Como testar cada parte](#como-testar-cada-parte)
- [Decisões de arquitetura e aprendizados](#decisões-de-arquitetura-e-aprendizados)
- [Testes automatizados e CI](#testes-automatizados-e-ci)
- [Limitações conhecidas e próximos passos](#limitações-conhecidas-e-próximos-passos)
- [Estrutura do repositório](#estrutura-do-repositório)
- [Licença](#licença)

---

## O que é este projeto

Quando um sistema de software (um site, um app, uma API) fica lento, para de responder, ou consome recursos demais, isso é chamado de **incidente**. Em qualquer empresa que opera software em produção existe uma equipe (frequentemente chamada de **SRE** — _Site Reliability Engineering_) responsável por perceber esses problemas rapidamente e corrigi-los antes que afetem muitos usuários.

O processo tradicional é assim: um alerta automático dispara, uma pessoa recebe a notificação, ela precisa **investigar** (métricas, logs, documentação interna de "o que fazer quando X acontece") e só então decidir e aplicar uma correção. Esse processo manual é lento e depende muito da experiência de quem está de plantão.

Este projeto constrói um **copiloto de IA** que automatiza a parte de _investigação e diagnóstico_: um sistema de múltiplos agentes que recebe o alerta automaticamente, busca numa base de conhecimento (runbooks) e propõe um diagnóstico e uma ação corretiva em segundos, ao invés de minutos ou horas.

**O ponto mais importante do projeto**: o sistema **nunca executa uma ação corretiva sozinho**. Ele só recomenda e uma pessoa real precisa revisar e aprovar antes de qualquer mudança de verdade acontecer (**human-in-the-loop**). Isso é essencial porque IA pode errar, e ações em produção (reiniciar um servidor, por exemplo) podem ter consequências sérias se aplicadas sem critério.

## Por que isso importa no mercado

Incidentes de produção custam caro, não só em receita perdida, mas no tempo (e estresse) da equipe técnica. Uma métrica muito usada na área é o **MTTR** (_Mean Time To Resolution_); reduzir esse tempo é prioridade constante em empresas de tecnologia. Existe um mercado inteiro para isso, chamado **AIOps** (_AI for IT Operations_). Dois exemplos de aplicação real:

- **E-commerce durante a Black Friday**: o checkout fica lento. Ao invés do time de plantão vasculhar dashboards na correria, o copiloto já aparece com "causa provável: esgotamento de conexões com o banco, ação recomendada: aumentar o pool", o humano só confirma.
- **SaaS com API usada por outros sistemas**: a API cai às 3h da manhã. O engenheiro de plantão (que acabou de acordar, sem contexto nenhum) recebe um diagnóstico inicial baseado nos runbooks da empresa, ao invés de começar do zero.

Este projeto é uma versão enxuta desse conceito, construída para eu aprender e demonstrar as peças técnicas por trás dele: observabilidade, RAG, sistemas multi-agente e aprovação humana.

## Arquitetura

```
app-fake (mede CPU real via cgroup + roda stress-ng sob demanda)
      │  scrape a cada 5s
      ▼
prometheus (avalia regras) ──alerta──▶ alertmanager (agrupa e envia)
                                              │  webhook HTTP POST
                                              ▼
                                    agent-orchestrator
                                    ┌─────────────────────────────┐
                                    │  LangGraph:                 │
                                    │  triagem → retrieval →      │
                                    │  diagnóstico → aprovação    │
                                    │  humana → execução da ação  │
                                    └─────────────────────────────┘
                                       │ consulta         │ estado
                                       ▼                  ▼
                                 rag-service         postgres-agent
                                       │
                                       ▼
                    runbooks/*.md → sentence-transformers → qdrant

                                       ▲
                                       │
                                  dashboard (Streamlit)
                        GET /processing, /pending, /incidents
                        POST /approve/{thread_id}
```

**Fluxo ponta a ponta**: um serviço monitorado (`app-fake`) expõe métricas → o Prometheus detecta anomalia e dispara um alerta → o Alertmanager notifica o `agent-orchestrator` → um grafo de 5 agentes (LangGraph) faz triagem, busca runbooks relevantes (RAG) e gera um diagnóstico com LLM → o grafo **pausa**, esperando um humano aprovar ou rejeitar pelo dashboard → só então (se aprovado) a ação corretiva é executada de verdade via Docker SDK.

## Stack técnica

| Camada                  | Tecnologia                                                            | Por quê                                                                                                                      |
| ----------------------- | --------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| Orquestração de agentes | **LangGraph**                                                         | Controle explícito de fluxo multi-agente + suporte nativo a pausar/retomar (`interrupt()`), essencial para human-in-the-loop |
| LLM                     | **Google Gemini API** (`gemma-4-31b-it`) via `langchain-google-genai` | Modelo de baixo custo, suficiente para tarefas estruturadas (com maior budget, melhor resultado)                             |
| RAG / busca semântica   | **Qdrant** + `sentence-transformers` (`all-MiniLM-L6-v2`)             | Embedding local (sem custo de API, sem dependência externa)                                                                  |
| Backend                 | **FastAPI** (Python)                                                  | Assíncrono, fácil de expor endpoints para agentes e aprovação humana                                                         |
| Persistência do grafo   | **PostgreSQL** (checkpointer do LangGraph)                            | Estado de um incidente pausado sobrevive a restarts do container                                                             |
| Observabilidade         | **Prometheus** + **Alertmanager**                                     | Padrão de mercado para métricas e alertas                                                                                    |
| Interface               | **Streamlit**                                                         | Dashboard funcional rápido, sem precisar de um frontend dedicado                                                             |
| Infraestrutura          | **Docker Compose**                                                    | Todos os serviços isolados e reproduzíveis em qualquer máquina                                                               |
| Testes / CI             | **pytest** + **GitHub Actions**                                       | Testes automatizados das partes puras do sistema, rodando a cada push                                                        |

## Como rodar

```bash
git clone git@github.com:Lucas-Darcio/Incident-Copilot.git
cd Incident-Copilot

cp .env.example .env
# edite o .env e preencha GOOGLE_API_KEY e POSTGRES_PASSWORD

docker compose up --build
```

> O primeiro build demora alguns minutos, pois o `rag-service` baixa o PyTorch (CPU-only) e o modelo de embedding durante a construção da imagem.

**Serviços disponíveis:**

| Serviço              | URL                             | Descrição                              |
| -------------------- | ------------------------------- | -------------------------------------- |
| `app-fake`           | http://localhost:8000/docs      | Serviço monitorado (simula incidentes) |
| `prometheus`         | http://localhost:9090           | Métricas e alertas                     |
| `alertmanager`       | http://localhost:9093           | Notificação de alertas                 |
| `agent-orchestrator` | http://localhost:8001/docs      | Grafo de agentes + API de aprovação    |
| `rag-service`        | http://localhost:8002/docs      | Busca semântica nos runbooks           |
| `qdrant`             | http://localhost:6333/dashboard | Vector database                        |
| `dashboard`          | http://localhost:8501           | **Painel de aprovação humana**         |

## Como testar cada parte

**1. Disparar um incidente real** (CPU alta por até 120s, contida por limite de recursos do container):

```bash
curl -X POST http://localhost:8000/chaos/start
```

Abra **http://localhost:8501** — o incidente aparece quase imediatamente com "🧠 Analisando...", e alguns segundos depois ganha diagnóstico completo e botões de aprovar/rejeitar.

**2. Testar sem esperar o Prometheus** (mais rápido, para desenvolvimento):

```bash
curl -X POST http://localhost:8001/diagnose \
  -H "Content-Type: application/json" \
  -d '{"alertname": "HighCPUUsage", "summary": "CPU alta em app-fake:8000",
       "description": "97% de uso", "severity": "critical", "instance": "app-fake:8000"}'

# copie o thread_id da resposta e aprove/rejeite:
curl -X POST http://localhost:8001/approve/SEU_THREAD_ID \
  -H "Content-Type: application/json" -d '{"approved": true}'
```

**3. Testar o RAG isoladamente:**

```bash
curl -X POST http://localhost:8002/ingest
curl -X POST http://localhost:8002/search \
  -H "Content-Type: application/json" \
  -d '{"query": "container consumindo muito processamento", "top_k": 3}'
```

Repare que a busca encontra o runbook certo mesmo sem a palavra "CPU" aparecer na pergunta, isso é busca semântica (por significado), não por palavra-chave.

## Decisões de arquitetura e aprendizados

Esta seção documenta as decisões técnicas mais importantes do projeto, e por quê. Organizado por tema, não por ordem cronológica de construção.

### Observabilidade e medição de recursos em containers

- **`cpu_usage_percent` é lido diretamente do cgroup do container** (o mesmo mecanismo que o `docker stats` usa), não via `psutil.cpu_percent()` puro. Motivo: dentro de um container Linux, `/proc/stat` ainda reflete a máquina host inteira, não o que foi alocado para aquele container, ou seja, usar `psutil` puro gera números artificialmente baixos que nunca cruzam o threshold de alerta.
- **A métrica é expressa como percentual do _próprio limite_ do container** (ex: 100% = usando toda a CPU alocada), não como percentual de um núcleo inteiro do host. É assim que ferramentas reais (cAdvisor, Kubernetes) calculam utilização, a pergunta certa é "está usando toda a capacidade que foi alocada?", não "quantos núcleos do host inteiro?".
- **`stress-ng` roda dentro do próprio container monitorado** (via subprocess), ao invés de um container de "chaos injection" externo. Isso mantém o comportamento determinístico e reprodutível em qualquer máquina, um container externo disputando núcleos físicos com outro é um cenário real ("vizinho barulhento"), mas seu resultado depende de quantos núcleos a máquina de quem roda o projeto tem, o que tornaria os testes inconsistentes.

### RAG: chunking e escolha de embeddings

- **Chunking por seção markdown** (`## Sintomas`, `## Ações recomendadas`, etc.), não por tamanho fixo de caracteres. Os runbooks já têm estrutura previsível, e cada seção já é semanticamente coesa por si só, o que evita cortar uma ideia no meio, um erro clássico de RAG mal feito.
- **Cada chunk é prefixado com o título do documento + nome da seção** antes de gerar o embedding (contextual chunking). Sem isso, uma seção como "Ações recomendadas: reiniciar o container" fica genérica demais isolada do resto do documento, o prefixo mantém o contexto semântico no vetor gerado.
- **Embedding local** (`sentence-transformers`, modelo `all-MiniLM-L6-v2`) ao invés de API paga (OpenAI/Cohere). É um modelo pequeno (~80MB), roda em CPU, sem custo recorrente e sem dependência de rede para essa etapa específica.

### Orquestração de agentes: por que LangGraph (não só LangChain "clássico")

O padrão antigo do LangChain (`AgentExecutor`, funcionava como um agente decidindo sozinho quais tools chamar em loop) hoje é construído **sobre o LangGraph por baixo dos panos** e a própria documentação do LangChain recomenda LangGraph para qualquer coisa além do trivial. Motivos concretos para este projeto:

- **Múltiplos agentes com papéis fixos** (triagem → retrieval → diagnóstico) mapeiam naturalmente para nós de um grafo com controle explícito.
- **Human-in-the-loop precisa de `interrupt()` + checkpointer** — não existe equivalente direto disso no `AgentExecutor` clássico.
- Tools, mensagens (`SystemMessage`/`HumanMessage`) e chat models continuam sendo LangChain puro — LangGraph é uma camada de orquestração por cima, não uma substituição.

### Custo e resiliência de chamadas a LLM

- **Deduplicação de alertas por `fingerprint`**: o Alertmanager reenvia um alerta `firing` periodicamente enquanto ele continuar ativo. Sem controle, isso chamaria o LLM de novo a cada reenvio do MESMO incidente. O `agent-orchestrator` ignora reenvios do mesmo fingerprint, liberando o controle apenas quando o alerta é `resolved`.
- **Parsing de JSON com múltiplas camadas de fallback**: modelos menores/mais baratos (como o Gemma usado aqui) ocasionalmente truncam ou geram JSON malformado. O parser tenta, em ordem: (1) JSON válido completo, (2) recuperação parcial via regex tolerante a strings truncadas, (3) fallback total com o texto bruto. Em todos os casos, **incerteza nunca vira automação**, então o campo `acao_automatizavel` cai para `false` por padrão sempre que não pode ser confirmado, sendo uma limitação do projeto.
- **Resposta assíncrona no webhook**: o campo `group_interval` do Alertmanager também define o timeout de espera pela resposta do webhook. Como o processamento (RAG + LLM) pode ultrapassar esse tempo, o `/webhook` responde imediatamente (aceitando o alerta) e processa em segundo plano (`BackgroundTasks`), evitando falsos "notify failed" no Alertmanager.

### Human-in-the-loop de verdade

- **`interrupt()` do LangGraph pausa o grafo** antes de qualquer ação corretiva, expondo o diagnóstico via `GET /pending`. A execução só continua com `POST /approve/{thread_id}` chamando `Command(resume=...)`.
- **Checkpointer Postgres** (não em memória): um incidente pode ficar pausado esperando aprovação por minutos ou horas, e o estado precisa sobreviver mesmo que o `agent-orchestrator` reinicie nesse meio tempo.
- **Auto-resolução de incidentes pendentes**: se o alerta original resolver sozinho (ex: o `stress-ng` atinge seu timeout) antes de qualquer decisão humana, o grafo é retomado automaticamente com `approved=False`, pois não faz sentido "corrigir" um problema que já desapareceu, e o incidente não fica pendente para sempre.
- **Nota de segurança**: o `agent-orchestrator` acessa o socket do Docker do host (`/var/run/docker.sock`) para executar ações reais. Isso equivale, na prática, a dar acesso root ao host para esse container, o que é aceitável para um projeto local de portfólio, mas em produção, obviamente, o recomendado é isolar isso atrás de uma API intermediária com allowlist restrita de comandos.

### Assincronia e experiência de uso

- **Estado "em análise" antes do diagnóstico ficar pronto**: a extração do resumo do alerta (`extrair_info_alerta`) é pura interpretação de texto, sem I/O, por isso é chamada imediatamente ao receber o alerta, e o dashboard mostra o incidente na hora (com um aviso de "🧠 Analisando...") ao invés de ficar "mudo" enquanto o RAG + LLM processam em segundo plano.

### Testabilidade: separar lógica pura de I/O

- **`parsing.py`** (agent-orchestrator) e **`chunking.py`** (rag-service) contêm só funções puras (sem chamadas de rede, sem LLM, sem Docker). Isso permite testar a lógica mais propensa a bugs, como parsing de respostas malformadas, chunking de markdown, com testes rápidos que não dependem de infraestrutura real.

## Testes automatizados e CI

```bash
# rag-service (rápido, sem PyTorch)
cd rag-service && pip install -r requirements-dev.txt && pytest tests/ -v

# agent-orchestrator (precisa das dependências completas)
cd agent-orchestrator
pip install -r requirements.txt -r requirements-dev.txt
GOOGLE_API_KEY=dummy pytest tests/ -v
```

Um workflow do GitHub Actions (`.github/workflows/tests.yml`) roda esses testes automaticamente a cada `push`/PR. Cobertura atual:

- `parsing.py`: extração de alerta, normalização de resposta do LLM, parsing de JSON válido/truncado/inválido
- `chunking.py`: divisão de runbooks por seção, casos-limite (documento vazio, seção vazia, sem título)
- `execute_action_node`: restart bem-sucedido, container não encontrado, ação rejeitada, ação não automatizável, falha genérica do Docker — tudo com um cliente Docker **mockado** (não precisa de acesso real ao socket para rodar os testes)

## Limitações conhecidas e próximos passos

Documentadas de propósito para mostrar que essas decisões foram conscientes, não esquecidas:

- **Sem autenticação**: qualquer pessoa com acesso à rede pode chamar `/approve` diretamente. Aceitável para um projeto local; em produção exigiria autenticação (API key, OAuth).
- **Sem expiração de incidentes pendentes**: se um incidente nunca for aprovado/rejeitado nem resolvido sozinho, ele fica pendente no Postgres indefinidamente. Um job de expiração por TTL seria o próximo passo natural.
- **Versões do LangChain/LangGraph não travadas**: o ecossistema muda muito rápido; travar via `pip freeze` é recomendado antes de qualquer uso mais sério além de portfólio.
- **Sem "vizinho barulhento" real**: o chaos engineering roda dentro do próprio container monitorado, não como carga externa disputando núcleos físicos (decisão consciente, ver seção de decisões acima).

## Estrutura do repositório

```
Incident-Copilot/
├── app-fake/              # Serviço monitorado (métricas + chaos engineering)
├── prometheus/            # Configuração de métricas e regras de alerta
├── alertmanager/          # Configuração de notificação de alertas
├── rag-service/           # Busca semântica (embeddings + Qdrant)
│   ├── chunking.py        #   lógica pura de chunking (testável)
│   └── tests/
├── agent-orchestrator/    # Grafo multi-agente (LangGraph) + API
│   ├── parsing.py         #   lógica pura de parsing (testável)
│   ├── graph.py           #   definição do grafo e dos 5 agentes
│   └── tests/
├── dashboard/             # Interface Streamlit de aprovação
├── runbooks/              # Base de conhecimento (markdown)
├── .github/workflows/     # CI (GitHub Actions)
├── docker-compose.yml
└── .env.example
```

## Licença

Este projeto está sob a licença MIT — veja [LICENSE](LICENSE).
