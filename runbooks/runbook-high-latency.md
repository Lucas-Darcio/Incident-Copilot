# Runbook: Latência alta nas requisições

## Sintomas
- Tempo de resposta médio ou p95/p99 acima do normal, mas o serviço
  continua respondendo (diferente de "fora do ar").
- Usuários relatam lentidão sem erros explícitos.
- Filas internas (se houver) começam a acumular itens.

## Causas prováveis
1. **Consulta lenta ao banco de dados**: falta de índice, query mal
   otimizada ou volume de dados maior que o esperado.
2. **Contenção de recursos**: CPU ou memória do container próximos do
   limite, causando processamento mais lento (correlacionar com os
   runbooks de CPU/memória altas).
3. **Dependência externa lenta**: chamada a uma API ou serviço externo
   com tempo de resposta degradado.
4. **Falta de paralelismo/conexões insuficientes**: pool de conexões
   (banco de dados, HTTP) muito pequeno, causando fila de espera
   interna antes mesmo de processar a requisição.

## Diagnóstico
1. Verifique se a latência está correlacionada com CPU ou memória alta
   no mesmo container (nesse caso, tratar como sintoma de outro
   runbook).
2. Meça a latência de cada dependência externa separadamente (banco,
   cache, APIs) para isolar onde está o gargalo.
3. Verifique o tamanho do pool de conexões configurado versus o volume
   de requisições simultâneas.

## Ações recomendadas
- **Se for gargalo de banco de dados**: revisar queries lentas e
  índices antes de qualquer ação de infraestrutura.
- **Se for contenção de recursos**: seguir o runbook correspondente
  (CPU ou memória alta).
- **Se for dependência externa lenta**: considerar timeout mais
  agressivo e fallback, para não propagar a lentidão para o usuário.
- **Mitigação temporária**: aumentar o pool de conexões pode aliviar o
  sintoma rapidamente, mas não substitui a investigação da causa raiz.

## Severidade
Média a alta, dependendo do impacto no tempo de resposta percebido
pelo usuário e se a tendência é de piora contínua.
