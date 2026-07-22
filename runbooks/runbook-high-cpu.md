# Runbook: CPU alta sustentada em serviço containerizado

## Sintomas
- Métrica `cpu_usage_percent` acima de 80% do limite alocado ao container
  por mais de 15 segundos.
- Tempo de resposta das requisições aumenta gradualmente.
- Em casos severos, o serviço para de responder a health checks.

## Causas prováveis
1. **Processo com loop ou cálculo ineficiente**: uma rotina interna do
   serviço passou a consumir CPU de forma desproporcional, geralmente
   após um deploy recente ou uma mudança de configuração.
2. **Aumento real de tráfego**: volume de requisições cresceu além da
   capacidade alocada para o container.
3. **Vizinho barulhento**: outro processo ou container no mesmo host
   físico está disputando os mesmos núcleos de CPU.
4. **Limite de recursos subdimensionado**: o container foi configurado
   com um teto de CPU (`cpus` no Docker Compose, ou `resources.limits`
   no Kubernetes) menor do que o necessário para sua carga normal.

## Diagnóstico
1. Confirme se o aumento de CPU coincide com um aumento de requisições
   (`http_requests_total`) ou se é desproporcional a ele.
2. Verifique se houve deploy ou mudança de configuração recente no
   serviço afetado.
3. Compare o uso de CPU do container com o uso da máquina/nó inteiro —
   se só o container está alto e a máquina está ociosa, é bug/config do
   serviço; se a máquina inteira está sob pressão, é problema de
   capacidade ou vizinho barulhento.

## Ações recomendadas
- **Se for pico de tráfego legítimo**: escalar horizontalmente (subir
  mais réplicas do serviço) ou aumentar o limite de CPU do container.
- **Se for processo travado/loop**: reiniciar o container costuma
  resolver o sintoma imediatamente, mas é preciso investigar a causa
  raiz depois (não tratar o restart como solução definitiva).
- **Se for vizinho barulhento**: mover o serviço para outro host ou
  isolar via `cpuset` (fixar núcleos dedicados).
- Nunca aumentar o limite de CPU sem entender a causa raiz — isso só
  adia o problema e pode mascarar um bug real.

## Severidade
Alta se persistir por mais de alguns minutos ou se afetar o tempo de
resposta ao usuário final. Média se for transitório e resolvido pela
própria autoescala.
