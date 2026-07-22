# Runbook: Uso de memória crescente (possível vazamento)

## Sintomas
- Métrica de uso de memória do container sobe de forma constante ao
  longo do tempo, sem estabilizar.
- O container é reiniciado pelo orquestrador por exceder o limite de
  memória (OOMKilled, no caso de Kubernetes/Docker).
- Aumento de latência pouco antes do crash, causado por garbage
  collection mais frequente (em linguagens com GC, como Python, Java,
  Node.js).

## Causas prováveis
1. **Vazamento de memória real**: objetos, conexões ou caches que nunca
   são liberados pela aplicação.
2. **Cache sem limite de tamanho**: uma estrutura de cache interna
   cresce indefinidamente porque não tem política de expiração (TTL)
   ou tamanho máximo.
3. **Acúmulo de conexões não fechadas**: conexões de banco de dados,
   HTTP ou filas que não são encerradas corretamente.
4. **Processamento de arquivos/payloads grandes**: a aplicação carrega
   arquivos inteiros na memória ao invés de processar em streaming.

## Diagnóstico
1. Observe se o crescimento de memória é linear e constante (indício
   forte de vazamento) ou se sobe e desce (comportamento normal de
   cache/GC).
2. Correlacione o início do crescimento com deploys recentes.
3. Se possível, capture um heap dump ou profile de memória no momento
   do pico para identificar quais objetos estão acumulando.

## Ações recomendadas
- **Mitigação imediata**: reiniciar o container libera a memória
  temporariamente, mas não resolve a causa raiz — deve ser tratado como
  paliativo, não solução.
- **Curto prazo**: adicionar limite de tamanho e TTL em caches internos.
- **Médio prazo**: revisar código em busca de conexões/recursos não
  fechados (usar context managers, connection pooling com limites).
- Monitorar a tendência de memória ao longo de dias, não só minutos —
  vazamentos lentos só ficam óbvios em janelas de tempo maiores.

## Severidade
Alta se o container está sendo reiniciado repetidamente (OOMKill em
loop). Média se o crescimento é lento e ainda há margem até o limite.
