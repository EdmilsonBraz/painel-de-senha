# Use Python 3.13 slim image
FROM python:3.13-slim

# Evita que o Python gere arquivos .pyc e permite logs em tempo real
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Define diretório de trabalho
WORKDIR /app

# Instala dependências do sistema necessárias para compilações leves se necessário
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copia e instala dependências do Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o restante da aplicação
COPY . .

# Expõe a porta que a aplicação usa (padrão 9000 no main.py)
EXPOSE 9000

# Comando para rodar a aplicação via Uvicorn (necessário para modo assíncrono e Socket.io)
CMD ["python", "main.py"]
