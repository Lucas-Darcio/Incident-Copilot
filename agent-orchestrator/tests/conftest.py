"""
Configuração compartilhada dos testes.

Importar `graph.py` exige que `ChatGoogleGenerativeAI` seja
instanciável (precisa de uma GOOGLE_API_KEY, mesmo que fake — a
validação de verdade só acontece quando o LLM é efetivamente chamado,
não na construção do objeto). Também garantimos que POSTGRES_URI NÃO
esteja definida, para o checkpointer cair no MemorySaver (em memória)
ao invés de tentar conectar a um Postgres real durante os testes.
"""
import os

os.environ.setdefault("GOOGLE_API_KEY", "fake-key-for-tests")
os.environ.pop("POSTGRES_URI", None)
