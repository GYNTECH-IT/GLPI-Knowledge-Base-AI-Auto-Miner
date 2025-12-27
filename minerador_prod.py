import mysql.connector
import requests
import json
import time
import re
import os
from dotenv import load_dotenv # Importe isso

# Carrega as senhas do arquivo .env
load_dotenv()

# ==============================================================================
# 1. CONFIGURAÇÕES (AGORA SEGURAS 🛡️)
# ==============================================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(BASE_DIR, "processed_tickets.txt")

# BANCO DE DADOS
DB_CONFIG = {
    'user': os.getenv('DB_USER'),      # Lê do .env
    'password': os.getenv('DB_PASS'),  # Lê do .env
    'database': os.getenv('DB_NAME'),
    'host': os.getenv('DB_HOST', 'localhost')
}

# INTELIGÊNCIA ARTIFICIAL
AI_CONFIG = {
    'key': os.getenv('AI_KEY'),
    'url': "https://openrouter.ai/api/v1/chat/completions",
    'site': "(SITE_URL)", #Dependendo do model é obrigatorio
    'model': os.getenv('AI_MODEL')
}

# API DO GLPI
GLPI_API = {
    'url': os.getenv('GLPI_URL'),
    'app_token': os.getenv('GLPI_APP_TOKEN'),
    'user_token': os.getenv('GLPI_USER_TOKEN')
}

# ==============================================================================
# 2. FUNÇÕES DE MEMÓRIA (HISTÓRICO)
# ==============================================================================

def load_history():
    """Carrega a lista de IDs já processados."""
    if not os.path.exists(HISTORY_FILE):
        return []
    with open(HISTORY_FILE, "r") as f:
        return [line.strip() for line in f.readlines()]

def save_history(ticket_id):
    """Salva o ID no histórico."""
    with open(HISTORY_FILE, "a") as f:
        f.write(f"{ticket_id}\n")

# ==============================================================================
# 3. FUNÇÕES DE IA E PARSE (JSON BLINDADO)
# ==============================================================================

def extract_json_smart(text):
    """Extrai JSON válido ignorando texto extra da DeepSeek."""
    text = re.sub(r'<think>[\s\S]*?</think>', '', text, flags=re.DOTALL)
    json_match = re.search(r'(\{[\s\S]*\})', text)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            return None
    return None

def generate_kb_article(ticket_title, ticket_solution):
    print(f"  -> [IA] Analisando: {ticket_title[:60]}...")
    
    prompt = f"""
    Atue como Especialista em Documentação de TI.
    Analise este chamado resolvido e crie um artigo para a Base de Conhecimento.

    PROBLEMA: {ticket_title}
    SOLUÇÃO APLICADA: {ticket_solution}

    REGRAS:
    1. É INCIDENTE? (Ex: WhatsApp caiu, Erro 404, Impressora) -> GERE O JSON.
    2. É PROJETO/REUNIÃO/TAREFA? -> RETORNE {{"ignorar": true}}.
    
    FORMATO JSON:
    {{
        "titulo": "Título Explicativo (Ex: Como corrigir falha no WhatsApp)",
        "conteudo": "<p>Passo a passo formatado em HTML...</p>",
        "ignorar": false
    }}
    """
    
    headers = {
        "Authorization": f"Bearer {AI_CONFIG['key']}",
        "HTTP-Referer": AI_CONFIG['site'],
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": AI_CONFIG['model'],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1
    }

    try:
        response = requests.post(AI_CONFIG['url'], headers=headers, json=payload)
        if response.status_code == 200:
            content = response.json()['choices'][0]['message']['content']
            return extract_json_smart(content)
        return None
    except Exception as e:
        print(f"  [ERRO IA] {e}")
        return None

# ==============================================================================
# 4. FUNÇÕES GLPI (BANCO E API)
# ==============================================================================

def get_db_tickets(port):
    """Busca tickets via SSH Tunnel."""
    conn = mysql.connector.connect(
        user=DB_CONFIG['user'], password=DB_CONFIG['password'],
        database=DB_CONFIG['database'], host='127.0.0.1', port=port
    )
    cursor = conn.cursor(dictionary=True)
    
    # Query de Incididentes (Ignora Projetos)
    query = """
    SELECT t.id, t.name, s.content as solucao
    FROM glpi_tickets t
    JOIN glpi_itilsolutions s ON s.items_id = t.id
    WHERE t.status = 6 
    AND t.is_deleted = 0 
    AND LENGTH(s.content) > 10
    AND t.name NOT LIKE '%Projeto%' 
    AND t.name NOT LIKE '%Deploy%'
    AND t.name NOT LIKE '%Reunião%'
    ORDER BY t.closedate DESC LIMIT 10
    """
    cursor.execute(query)
    res = cursor.fetchall()
    conn.close()
    return res

def glpi_init_session():
    """Autentica na API Pública."""
    headers = {
        "App-Token": GLPI_API['app_token'],
        "Authorization": f"user_token {GLPI_API['user_token']}"
    }
    try:
        # Tenta conectar na URL pública oficial
        resp = requests.get(f"{GLPI_API['url']}/initSession", headers=headers)
        if resp.status_code == 200:
            token = resp.json().get('session_token')
            print(f"[API] Login realizado! Token: {token[:10]}...")
            return token
        else:
            print(f"[ERRO API] Login negado ({resp.status_code}): {resp.text}")
    except Exception as e:
        print(f"[ERRO CONEXÃO API] {e}")
    return None

def glpi_kill_session(session_token):
    headers = {"App-Token": GLPI_API['app_token'], "Session-Token": session_token}
    requests.get(f"{GLPI_API['url']}/killSession", headers=headers)

def post_article_to_glpi(session_token, kb_data, source_ticket_id):
    """Envia o artigo para o GLPI (Modo Rascunho)."""
    headers = {
        "App-Token": GLPI_API['app_token'],
        "Session-Token": session_token,
        "Content-Type": "application/json"
    }
    
    # Adiciona rodapé de autoria da IA
    html_content = kb_data['conteudo'] + \
                   f"<br><hr><p style='font-size: small; color: gray;'><i>Artigo gerado automaticamente pela IA a partir do Chamado #{source_ticket_id}.</i></p>"

    payload = {
        "input": {
            "name": kb_data['titulo'],
            "answer": html_content,
            "is_faq": 0,    # 0 = Não publicar na FAQ ainda
            "is_active": 0, # 0 = INATIVO (Rascunho)
        }
    }

    try:
        resp = requests.post(f"{GLPI_API['url']}/KnowbaseItem", headers=headers, json=payload)
        
        if resp.status_code == 201: # 201 Created
            new_id = resp.json()['id']
            print(f"  -> [SUCESSO 🚀] Artigo criado no GLPI! ID: {new_id} (Status: Inativo)")
            return True
        else:
            print(f"  -> [ERRO API] Falha ao criar: {resp.status_code} - {resp.text}")
            return False
    except Exception as e:
        print(f"  -> [ERRO POST] {e}")
        return False

# ==============================================================================
# 5. EXECUÇÃO
# ==============================================================================

if __name__ == "__main__":
    print("--- INICIANDO MINERADOR (MODO PRODUÇÃO) ---")
    
    processed_ids = load_history()
    print(f"[MEMÓRIA] {len(processed_ids)} chamados ignorados (já processados).")

    try:
        with SSHTunnelForwarder(
            (SSH_CONFIG['ssh_address_or_host'], 22),
            ssh_username=SSH_CONFIG['ssh_username'],
            ssh_password=SSH_CONFIG['ssh_password'],
            remote_bind_address=('127.0.0.1', 3306)
        ) as server:
            
            # 1. Busca no Banco
            tickets = get_db_tickets(server.local_bind_port)
            print(f"[DB] {len(tickets)} tickets recentes analisados.")

            # 2. Filtra Duplicados
            novos_tickets = [t for t in tickets if str(t['id']) not in processed_ids]
            
            if not novos_tickets:
                print("-> Nada novo para processar hoje.")
                exit()

            print(f"[FILTRO] {len(novos_tickets)} chamados inéditos para a IA.")

            # 3. Login API GLPI
            session_token = glpi_init_session()
            if not session_token:
                exit()
                
            # 4. Processamento IA -> GLPI
            for t in novos_tickets:
                kb_data = generate_kb_article(t['name'], t['solucao'])
                
                if kb_data and not kb_data.get('ignorar'):
                    sucesso = post_article_to_glpi(session_token, kb_data, t['id'])
                    if sucesso:
                        save_history(t['id']) # Grava na memória
                else:
                    print(f"  -> Ticket #{t['id']} ignorado (Projeto ou irrelevante).")
                
                time.sleep(3) # Pausa leve
                
            glpi_kill_session(session_token)
            
    except Exception as e:
        print(f"[ERRO CRÍTICO] {e}")
        
    print("\n--- FIM DO PROCESSO ---")
    print("👉 Vá no GLPI > Base de Conhecimento > Filtre por 'Não Publicados' para ver os rascunhos.")