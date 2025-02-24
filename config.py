import os
from dotenv import load_dotenv
from dataclasses import dataclass

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()

@dataclass
class BlingConfig:
    """Configuração para API do Bling"""
    api_key: str
    base_url: str

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
class Settings:
    """Configurações globais da aplicação"""
    bling: BlingConfig
    whatsapp: WhatsAppConfig
    group: WhatsAppGroup
    check_interval: int

def load_settings() -> Settings:
    """Carrega todas as configurações do arquivo .env"""
    return Settings(
        bling=BlingConfig(
            api_key=os.getenv('BLING_API_KEY'),
            base_url=os.getenv('BLING_API_URL', 'https://bling.com.br/Api/v2')
        ),
        whatsapp=WhatsAppConfig(
            api_key=os.getenv('WHATSAPP_API_KEY'),
            api_url=os.getenv('WHATSAPP_API_URL'),
            instance=os.getenv('WHATSAPP_INSTANCE')
        ),
        group=WhatsAppGroup(
            group_id=os.getenv('WHATSAPP_GROUP_ID'),
            name=os.getenv('WHATSAPP_GROUP_NAME', 'Alertas de Estoque')
        ),
        check_interval=int(os.getenv('CHECK_INTERVAL', 30))
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
    
    for value, name in required_settings:
        if not value:
            print(f"Erro: Configuração {name} não encontrada no arquivo .env")
            return False
    return True