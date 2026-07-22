FROM python:3.12-slim

WORKDIR /app

# Instalamos o torch em sua versão "CPU-only" primeiro. Por padrão o
# PyPI instalaria a versão com suporte a GPU/CUDA, que é muito maior
# e desnecessária aqui, já que rodamos o modelo de embedding em CPU.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Baixa e cacheia o modelo de embedding DURANTE o build da imagem, não
# na primeira requisição — assim o container já sobe pronto para uso,
# sem esperar um download na hora de responder ao usuário.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

COPY main.py .

EXPOSE 8002

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
