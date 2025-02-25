#config.py
import os
import pathlib
from dotenv import load_dotenv
from dataclasses import dataclass

# Tentar carregar o .env com caminho explícito
current_dir = pathlib.Path().absolute()
env_path = pathlib.Path(current_dir, '.env')
print(f"Tentando carregar .env de: {env_path}")
load_dotenv(dotenv_path=env_path)

# Define valores fixos para o grupo (isso vai funcionar independente do .env)
WHATSAPP_GROUP_ID = "120363296510746112@g.us"
WHATSAPP_GROUP_NAME = "Estoque - Luar Shop"

@dataclass
class BlingConfig:
    """Configuração para API do Bling"""
    api_key: str
    base_url: str
    # Novas configurações para o OAuth
    client_id: str = None
    client_secret: str = None

@dataclass
class WhatsAppConfig:
    """Configuração para Evolution API"""
    api_key: str
    api_url: str
    instance: str

@dataclass
class WhatsAppGroup:
    """Configuração do grupo do WhatsApp"""
    group_id: str
    name: str

@dataclass
class GroqConfig:
    """Configuração para API Groq (LLM)"""
    api_key: str

@dataclass
class Settings:
    """Configurações globais da aplicação"""
    bling: BlingConfig
    whatsapp: WhatsAppConfig
    group: WhatsAppGroup
    check_interval: int
    groq: GroqConfig = None  # Opcional, pode não estar configurado

def load_settings() -> Settings:
    """Carrega todas as configurações do arquivo .env"""
    # Usa valores das variáveis de ambiente, mas sobrescreve com os valores fixos do grupo
    return Settings(
        bling=BlingConfig(
            api_key=os.getenv('BLING_API_KEY', ''),
            base_url=os.getenv('BLING_API_URL', 'https://bling.com.br/Api/v3'),
            client_id=os.getenv('BLING_CLIENT_ID', ''),
            client_secret=os.getenv('BLING_CLIENT_SECRET', '')
        ),
        whatsapp=WhatsAppConfig(
            api_key=os.getenv('WHATSAPP_API_KEY', '429683C4C977415CAAFCCE10F7D57E11'),
            api_url=os.getenv('WHATSAPP_API_URL', 'https://evo.ariondigital.com.br'),
            instance=os.getenv('WHATSAPP_INSTANCE', 'Luar Shop')
        ),
        group=WhatsAppGroup(
            # Usa os valores fixos definidos acima
            group_id=WHATSAPP_GROUP_ID,
            name=WHATSAPP_GROUP_NAME
        ),
        check_interval=int(os.getenv('CHECK_INTERVAL', 30)),
        groq=GroqConfig(
            api_key=os.getenv('GROQ_API_KEY', '')
        ) if os.getenv('GROQ_API_KEY') else None
    )

def validate_settings(settings: Settings) -> bool:
    """Valida se todas as configurações necessárias estão presentes"""
    required_settings = [
        (settings.bling.api_key, 'BLING_API_KEY'),
        (settings.whatsapp.api_key, 'WHATSAPP_API_KEY'),
        (settings.whatsapp.api_url, 'WHATSAPP_API_URL'),
        (settings.whatsapp.instance, 'WHATSAPP_INSTANCE'),
        (settings.group.group_id, 'WHATSAPP_GROUP_ID')
    ]
    
    # As novas configurações não são obrigatórias para que o sistema original continue funcionando
    # Elas são verificadas separadamente quando tentamos inicializar o agente de estoque
    
    for value, name in required_settings:
        if not value:
            print(f"Erro: Configuração {name} não encontrada no arquivo .env")
            return False
    return True