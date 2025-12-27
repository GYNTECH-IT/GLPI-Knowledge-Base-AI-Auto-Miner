# GLPI Knowledge Base AI Auto-Miner 🤖📚

Automação em Python que monitora chamados resolvidos no GLPI, utiliza IA (DeepSeek) para transformar soluções técnicas breves em tutoriais HTML completos e publica automaticamente na Base de Conhecimento.

## 🚀 Arquitetura


**Fluxo:**
1. **Monitoramento:** Script Python lê banco MySQL do GLPI.
2. **IA:** Envia dados para DeepSeek via OpenRouter.
3. **Publicação:** Cria artigo Rascunho via API REST do GLPI.

## 🛠️ Instalação

1. Clone o repositório.
2. Instale as dependências: `pip install -r requirements.txt`
3. Crie um arquivo `.env` baseado no exemplo.
4. Configure no Crontab da VPS.

## 🛡️ Segurança
Este projeto utiliza variáveis de ambiente. Renomeie `.env.example` para `.env` e preencha suas chaves.