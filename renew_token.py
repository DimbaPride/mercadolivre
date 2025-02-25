#!/usr/bin/env python3
"""
Script para renovar forçadamente o token do Bling

Uso:
    python3 renew_token.py
"""

import os
import asyncio
import logging
from dotenv import load_dotenv
from token_manager import BlingTokenManager

# Configuração de logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("token_renewer")

async def main():
    # Carrega variáveis de ambiente do .env
    load_dotenv()
    
    # Obtém credenciais
    client_id = os.environ.get("BLING_CLIENT_ID")
    client_secret = os.environ.get("BLING_CLIENT_SECRET")
    
    if not client_id or not client_secret:
        logger.error("❌ Variáveis BLING_CLIENT_ID e BLING_CLIENT_SECRET não encontradas no .env")
        return False
    
    logger.info("🔄 Iniciando renovação forçada de token...")
    
    # Cria o gerenciador de token
    token_manager = BlingTokenManager(
        client_id=client_id,
        client_secret=client_secret
    )
    
    # Força renovação
    success = await token_manager.refresh_token()
    
    if success:
        logger.info("✅ Token renovado com sucesso!")
        
        # Exibe informações do token para verificação
        with open("bling_token.json", "r") as f:
            import json
            token_data = json.load(f)
            
            # Mostra apenas parte do token por segurança
            if "access_token" in token_data:
                masked_token = token_data["access_token"][:15] + "..." 
                logger.info(f"Token: {masked_token}")
                
            # Mostra tempo de expiração
            if "expires_in" in token_data:
                logger.info(f"Expira em: {token_data['expires_in']} segundos")
                
            # Mostra quando foi criado
            if "created_at" in token_data:
                from datetime import datetime
                created_time = datetime.fromtimestamp(token_data["created_at"])
                logger.info(f"Criado em: {created_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        return True
    else:
        logger.error("❌ Falha ao renovar token!")
        return False

if __name__ == "__main__":
    asyncio.run(main())