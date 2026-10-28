import sqlite3
import json
from typing import Dict, Any
import streamlit as st
from openai import AzureOpenAI

# Configuração da Página
st.set_page_config(
    page_title="HardwareBot - Azure AI",
    layout="centered",
    initial_sidebar_state="expanded"
)

DB_NAME = "loja_hardware.db"

# ==========================================
# 1. CONFIGURAÇÕES DA AZURE OPENAI
# ==========================================
AZURE_ENDPOINT_DEFAULT = "https://aziaa.openai.azure.com/"
AZURE_API_KEY_DEFAULT = ""
AZURE_DEPLOYMENT_DEFAULT = "gpt-5-mini"
AZURE_API_VERSION = "2024-02-15-preview"

st.sidebar.title("⚙️ Configuração Azure AI")

azure_endpoint = st.sidebar.text_input(
    "Azure Endpoint:",
    value=AZURE_ENDPOINT_DEFAULT,
    placeholder="https://seu-recurso.openai.azure.com/",
    help="O endpoint do seu recurso Azure OpenAI."
)

azure_api_key = st.sidebar.text_input(
    "Azure API Key:",
    value=AZURE_API_KEY_DEFAULT,
    type="password",
    help="A chave de API gerada no portal da Azure."
)

azure_deployment = st.sidebar.text_input(
    "Deployment Name:",
    value=AZURE_DEPLOYMENT_DEFAULT,
    placeholder="ex: gpt-35-turbo",
    help="O nome exato do Deployment criado no Azure AI Studio."
)

# Inicializa o cliente AzureOpenAI
client = None
if azure_endpoint and azure_api_key and azure_deployment:
    try:
        client = AzureOpenAI(
            azure_endpoint=azure_endpoint,
            api_key=azure_api_key,
            api_version=AZURE_API_VERSION
        )
    except Exception as e:
        st.sidebar.error(f"Erro ao inicializar cliente Azure: {e}")


# ==========================================
# 2. CAMADA DE DADOS E FERRAMENTAS (SQLite)
# ==========================================

def inicializar_banco() -> None:
    """Cria a tabela de produtos e insere dados de teste se não existirem."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS produtos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            preco REAL NOT NULL,
            estoque INTEGER NOT NULL
        )
    """)
    
    cursor.execute("SELECT COUNT(*) FROM produtos")
    if cursor.fetchone()[0] == 0:
        produtos_iniciais = [
            ("Placa de Vídeo RTX 4060", 2199.90, 10),
            ("Processador Ryzen 5 7600X", 1450.00, 15),
            ("Memória RAM 16GB DDR5", 480.00, 25),
            ("SSD NVMe 1TB M.2", 420.00, 30),
            ("Placa Mãe B650M", 950.00, 8)
        ]
        cursor.executemany("INSERT INTO produtos (nome, preco, estoque) VALUES (?, ?, ?)", produtos_iniciais)
        conn.commit()
    conn.close()


def consultar_estoque(item_id: int) -> str:
    """Consulta o estoque e detalhes de um produto específico no banco de dados."""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT id, nome, preco, estoque FROM produtos WHERE id = ?", (item_id,))
        produto = cursor.fetchone()
        conn.close()

        if produto:
            return json.dumps({
                "status": "sucesso",
                "item_id": produto[0],
                "nome": produto[1],
                "preco": produto[2],
                "estoque": produto[3]
            }, ensure_ascii=False)
        else:
            return json.dumps({"status": "erro", "mensagem": f"Produto com ID {item_id} não encontrado."}, ensure_ascii=False)
            
    except sqlite3.Error as e:
        return json.dumps({"status": "erro", "mensagem": f"Erro no banco: {str(e)}"}, ensure_ascii=False)


def reservar_produto(item_id: int, quantidade: int) -> str:
    """Realiza a baixa ou reserva de uma quantidade específica de um produto no estoque."""
    if quantidade <= 0:
        return json.dumps({"status": "erro", "mensagem": "A quantidade deve ser maior que zero."}, ensure_ascii=False)

    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT nome, estoque FROM produtos WHERE id = ?", (item_id,))
        produto = cursor.fetchone()

        if not produto:
            conn.close()
            return json.dumps({"status": "erro", "mensagem": f"Produto ID {item_id} não encontrado."}, ensure_ascii=False)

        nome, estoque_atual = produto

        if estoque_atual < quantidade:
            conn.close()
            return json.dumps({
                "status": "erro",
                "mensagem": f"Estoque insuficiente para '{nome}'. Disponível: {estoque_atual}, solicitado: {quantidade}."
            }, ensure_ascii=False)

        novo_estoque = estoque_atual - quantidade
        cursor.execute("UPDATE produtos SET estoque = ? WHERE id = ?", (novo_estoque, item_id))
        conn.commit()
        conn.close()

        return json.dumps({
            "status": "sucesso",
            "mensagem": f"Reserva realizada com sucesso para {quantidade} unidade(s) de '{nome}'.",
            "novo_estoque": novo_estoque
        }, ensure_ascii=False)

    except sqlite3.Error as e:
        return json.dumps({"status": "erro", "mensagem": f"Erro interno: {str(e)}"}, ensure_ascii=False)


# Inicializa a base de dados
inicializar_banco()


# ==========================================
# 3. INTERFACE DE CHAT E INTEGRAÇÃO AZURE
# ==========================================

st.title("💻 HardwareBot - Agente com Azure AI")
st.markdown("Assistente inteligente integrado ao **Azure OpenAI** para consulta e reserva de peças em tempo real.")

# Barra lateral - Visualização do Inventário
st.sidebar.markdown("---")
st.sidebar.header("📦 Inventário Atual (SQLite)")
try:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, nome, preco, estoque FROM produtos")
    for p in cursor.fetchall():
        st.sidebar.text(f"ID {p[0]}: {p[1]}\nR$ {p[2]:.2f} | Est: {p[3]}")
        st.sidebar.markdown("---")
    conn.close()
except Exception:
    pass

# Mapeamento de Funções (Tools) para Azure OpenAI
tools = [
    {
        "type": "function",
        "function": {
            "name": "consultar_estoque",
            "description": "Consulta a disponibilidade, preço e nome de um produto específico no banco de dados SQLite pelo seu ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "integer", "description": "O ID numérico do produto."}
                },
                "required": ["item_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "reservar_produto",
            "description": "Realiza a baixa/reserva de unidades de um produto no estoque do banco de dados pelo seu ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "integer", "description": "O ID numérico do produto."},
                    "quantidade": {"type": "integer", "description": "A quantidade de unidades a reservar."}
                },
                "required": ["item_id", "quantidade"]
            }
        }
    }
]

# Inicializa histórico da conversa
if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "system",
            "content": "Você é o HardwareBot, um assistente virtual especialista em suporte logístico e comercial de uma loja de componentes de computador. Sua missão é auxiliar usuários a consultarem preços e disponibilidades de produtos no catálogo, além de realizar reservas de itens utilizando as ferramentas disponíveis."
        }
    ]

# Exibe histórico na tela tratado para dicionários e objetos
for message in st.session_state.messages:
    role = message["role"] if isinstance(message, dict) else getattr(message, "role", None)
    content = message["content"] if isinstance(message, dict) else getattr(message, "content", None)
    
    if role != "system" and content:
        with st.chat_message(role):
            st.markdown(content)

# Entrada de chat
if prompt := st.chat_input("Ex: 'Qual o estoque da peça ID 1?' ou 'Reserve 2 unidades do produto ID 2'"):
    if not client:
        st.warning("⚠️ Preencha as configurações da Azure OpenAI (Endpoint, API Key e Deployment Name) na barra lateral.")
    else:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            try:
                # 1ª Chamada para a API da Azure OpenAI
                response = client.chat.completions.create(
                    model=azure_deployment,  
                    messages=st.session_state.messages,
                    tools=tools,
                    tool_choice="auto"
                )
                
                response_message = response.choices[0].message
                tool_calls = response_message.tool_calls

                # Verifica se a IA solicitou execução de ferramentas (Function Calling)
                if tool_calls:
                    st.session_state.messages.append(response_message)
                    
                    for tool_call in tool_calls:
                        function_name = tool_call.function.name
                        function_args = json.loads(tool_call.function.arguments)
                        
                        if function_name == "consultar_estoque":
                            function_response = consultar_estoque(item_id=function_args.get("item_id"))
                        elif function_name == "reservar_produto":
                            function_response = reservar_produto(
                                item_id=function_args.get("item_id"),
                                quantidade=function_args.get("quantidade")
                            )
                        else:
                            function_response = json.dumps({"erro": "Função não encontrada."})

                        # Adiciona o retorno da função ao contexto
                        st.session_state.messages.append({
                            "tool_call_id": tool_call.id,
                            "role": "tool",
                            "name": function_name,
                            "content": function_response,
                        })

                    # 2ª Chamada para a Azure para gerar a resposta textual baseada no retorno da ferramenta
                    second_response = client.chat.completions.create(
                        model=azure_deployment,
                        messages=st.session_state.messages,
                    )
                    
                    final_reply = second_response.choices[0].message.content
                    st.markdown(final_reply)
                    st.session_state.messages.append({"role": "assistant", "content": final_reply})
                    st.rerun()  # Atualiza a barra lateral com o estoque atualizado
                
                else:
                    final_reply = response_message.content
                    st.markdown(final_reply)
                    st.session_state.messages.append({"role": "assistant", "content": final_reply})

            except Exception as e:
                st.error(f"Erro na comunicação com a Azure OpenAI: {e}")