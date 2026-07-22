# Runbook: Serviço não responde a health checks (fora do ar)

## Sintomas
- Endpoint de health check (`/health`) para de responder ou passa a
  retornar erro.
- Requisições dos clientes retornam timeout ou erro de conexão recusada.
- Orquestrador (Docker/Kubernetes) marca o container como não saudável.

## Causas prováveis
1. **Crash da aplicação**: exceção não tratada derrubou o processo
   principal.
2. **Deadlock ou travamento**: o processo está vivo, mas não consegue
   mais processar requisições (thread pool esgotado, lock nunca
   liberado).
3. **Dependência externa indisponível**: o serviço trava esperando
   resposta de um banco de dados, fila ou API externa que está fora do
   ar, sem timeout configurado.
4. **Esgotamento de recursos**: falta de memória ou file descriptors
   disponíveis impede o processo de aceitar novas conexões.

## Diagnóstico
1. Verifique se o processo/container ainda está rodando ou já
   reiniciou sozinho (reinícios recorrentes indicam crash, não
   travamento).
2. Consulte os logs mais recentes do container em busca de stack
   traces ou mensagens de erro no momento em que parou de responder.
3. Verifique o status das dependências externas (banco de dados, cache,
   filas) que o serviço consome.
4. Se o processo está vivo mas não responde, um travamento
   (deadlock/thread pool esgotado) é mais provável que um crash.

## Ações recomendadas
- **Se for crash**: reiniciar resolve o sintoma imediato; analisar o
  stack trace do log para identificar a exceção raiz.
- **Se for dependência externa fora do ar**: a correção real é na
  dependência, não no serviço afetado — mas adicionar timeout e
  circuit breaker evita que uma falha externa trave o serviço inteiro
  no futuro.
- **Se for esgotamento de recursos**: verificar limites de memória,
  conexões e file descriptors configurados versus o necessário.
- Sempre confirmar que o serviço voltou a responder corretamente após
  qualquer ação corretiva, não apenas que o container reiniciou.

## Severidade
Crítica — impacto direto e imediato no usuário final. Deve ser tratada
com prioridade máxima.
