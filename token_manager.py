import json
import os
import time
import logging
import asyncio
import threading
from datetime import datetime, timedelta
import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv

# Configuração de logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("bling_token_manager")

class BlingTokenManager:
    """
    Gerenciador de token para API Bling v3
    - Gerencia renovação automática de tokens
    - Verifica validade de tokens antes de requisições
    - Inicializa um job em background para renovação periódica
    """
    
    def __init__(self, client_id, client_secret, token_file="bling_token.json", env_file=".env"):
        """
        Inicializa o gerenciador de tokens
        
        :param client_id: Client ID do aplicativo Bling
        :param client_secret: Client Secret do aplicativo Bling
        :param token_file: Arquivo para armazenar os dados do token
        :param env_file: Arquivo .env para atualizar a variável BLING_API_KEY
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_file = token_file
        self.env_file = env_file
        self.token_url = "https://www.bling.com.br/Api/v3/oauth/token"
        
        # Dados do token em memória
        self._token_data = None
        self._token_lock = threading.Lock()
        
        # Carrega token do arquivo, se existir
        self._load_token()
        
        # Flag para controlar o job de renovação
        self._renewal_running = False
        self._renewal_task = None
        
        logger.info("Gerenciador de token Bling inicializado")
    
    def _load_token(self):
        """Carrega os dados do token do arquivo"""
        try:
            if os.path.exists(self.token_file):
                with open(self.token_file, "r") as file:
                    self._token_data = json.load(file)
                logger.info("Token carregado do arquivo")
            else:
                logger.warning(f"Arquivo de token {self.token_file} não encontrado")
        except Exception as e:
            logger.error(f"Erro ao carregar token: {str(e)}")
    
    def _save_token(self):
        """Salva os dados do token no arquivo"""
        try:
            with self._token_lock:
                with open(self.token_file, "w") as file:
                    json.dump(self._token_data, file, indent=2)
                
                # Atualiza o arquivo .env
                self._update_env_file()
                
            logger.info("Token salvo no arquivo")
        except Exception as e:
            logger.error(f"Erro ao salvar token: {str(e)}")
    
    def _update_env_file(self):
        """Atualiza a variável BLING_API_KEY no arquivo .env"""
        try:
            if not self._token_data or "access_token" not in self._token_data:
                return
            
            access_token = self._token_data["access_token"]
            
            # Se o arquivo .env não existir, cria
            if not os.path.exists(self.env_file):
                with open(self.env_file, "w") as env_file:
                    env_file.write(f"BLING_API_KEY={access_token}\n")
                return
            
            # Lê o arquivo .env
            with open(self.env_file, "r") as env_file:
                lines = env_file.readlines()
            
            # Verifica se a variável já existe
            bling_api_key_exists = False
            updated_lines = []
            
            for line in lines:
                if line.startswith("BLING_API_KEY="):
                    updated_lines.append(f"BLING_API_KEY={access_token}\n")
                    bling_api_key_exists = True
                else:
                    updated_lines.append(line)
            
            # Se a variável não existir, adiciona
            if not bling_api_key_exists:
                updated_lines.append(f"BLING_API_KEY={access_token}\n")
            
            # Escreve o arquivo atualizado
            with open(self.env_file, "w") as env_file:
                env_file.writelines(updated_lines)
            
            # Também atualiza a variável de ambiente atual
            os.environ["BLING_API_KEY"] = access_token
            
            logger.info("Arquivo .env atualizado com o novo token")
        except Exception as e:
            logger.error(f"Erro ao atualizar arquivo .env: {str(e)}")
    
    async def refresh_token(self):
        """
        Renova o token usando o refresh_token
        
        :return: True se renovado com sucesso, False caso contrário
        """
        try:
            with self._token_lock:
                # Verifica se temos dados de token
                if not self._token_data or "refresh_token" not in self._token_data:
                    logger.error("Dados de token inexistentes ou incompletos")
                    return False
                
                refresh_token = self._token_data["refresh_token"]
            
            # Prepara a requisição
            headers = {
                "Content-Type": "application/x-www-form-urlencoded"
            }
            
            payload = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token
            }
            
            # Autenticação HTTP Basic
            auth = HTTPBasicAuth(self.client_id, self.client_secret)
            
            # Faz a requisição de forma síncrona
            response = requests.post(
                self.token_url,
                data=payload,
                headers=headers,
                auth=auth,
                timeout=10
            )
            
            if response.status_code == 200:
                new_token_data = response.json()
                
                with self._token_lock:
                    self._token_data = new_token_data
                
                # Salva o token
                self._save_token()
                
                logger.info(f"Token renovado com sucesso, expira em {new_token_data.get('expires_in', 'N/A')} segundos")
                return True
            else:
                logger.error(f"Erro ao renovar token: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Erro durante renovação do token: {str(e)}")
            return False
    
    async def get_valid_token(self):
        """
        Obtém um token válido, renovando se necessário
        
        :return: Token de acesso válido ou None se não for possível obter
        """
        with self._token_lock:
            # Se não temos dados de token, não podemos fazer nada
            if not self._token_data or "access_token" not in self._token_data:
                logger.error("Não há token disponível")
                return None
            
            # Verifica se o token está próximo de expirar (menos de 10 minutos)
            expires_in = self._token_data.get("expires_in", 0)
            expiry_threshold = 600  # 10 minutos em segundos
            
            if expires_in < expiry_threshold:
                # Token está próximo de expirar, renova
                logger.info("Token próximo da expiração, renovando...")
                
                # Libera o lock antes de chamar refresh_token para evitar deadlock
                # já que refresh_token adquire o lock internamente
            
        # Tenta renovar o token
        if expires_in < expiry_threshold:
            success = await self.refresh_token()
            if not success:
                logger.warning("Falha ao renovar token, usando o atual mesmo assim")
        
        # Retorna o token atual (renovado ou não)
        with self._token_lock:
            return self._token_data.get("access_token")
    
    def start_renewal_job(self, interval_hours=5):
        """
        Inicia um job em background para renovação periódica do token
        
        :param interval_hours: Intervalo em horas para renovação
        """
        if self._renewal_running:
            logger.info("Job de renovação já está em execução")
            return
        
        self._renewal_running = True
        
        async def renewal_job():
            """Job assíncrono para renovação periódica"""
            logger.info(f"Iniciando job de renovação a cada {interval_hours} horas")
            
            while self._renewal_running:
                try:
                    # Espera pelo intervalo (em segundos)
                    await asyncio.sleep(interval_hours * 60 * 60)
                    
                    # Renova o token
                    logger.info("Executando renovação programada do token")
                    await self.refresh_token()
                    
                except asyncio.CancelledError:
                    logger.info("Job de renovação cancelado")
                    break
                except Exception as e:
                    logger.error(f"Erro no job de renovação: {str(e)}")
                    # Continua tentando após erro
                    await asyncio.sleep(60)  # Espera 1 minuto antes de tentar novamente
        
        # Inicia o job de renovação como uma tarefa assíncrona
        self._renewal_task = asyncio.create_task(renewal_job())
        logger.info("Job de renovação iniciado")
    
    def stop_renewal_job(self):
        """Para o job de renovação periódica"""
        if not self._renewal_running:
            return
        
        self._renewal_running = False
        
        if self._renewal_task:
            self._renewal_task.cancel()
            logger.info("Job de renovação cancelado")
    
    async def ensure_token_file_exists(self, auth_code=None):
        """
        Garante que o arquivo de token existe, criando-o se necessário
        
        :param auth_code: Código de autorização para obter o token inicial
        :return: True se o arquivo existe ou foi criado, False caso contrário
        """
        # Se o arquivo já existe, apenas retorna
        if os.path.exists(self.token_file):
            return True
        
        # Se não temos código de autorização, não podemos criar o arquivo
        if not auth_code:
            logger.error("Arquivo de token não existe e nenhum código de autorização fornecido")
            return False
        
        # Tenta obter o token inicial
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        payload = {
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": "https://530f-45-171-45-13.ngrok-free.app/callback"  # Use a URL de callback do seu app
        }
        
        # Autenticação HTTP Basic
        auth = HTTPBasicAuth(self.client_id, self.client_secret)
        
        try:
            response = requests.post(
                self.token_url,
                data=payload,
                headers=headers,
                auth=auth,
                timeout=10
            )
            
            if response.status_code == 200:
                token_data = response.json()
                
                with self._token_lock:
                    self._token_data = token_data
                
                # Salva o token
                self._save_token()
                
                logger.info("Token inicial obtido e salvo com sucesso")
                return True
            else:
                logger.error(f"Erro ao obter token inicial: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Erro ao obter token inicial: {str(e)}")
            return False


# Exemplo de uso
if __name__ == "__main__":
    # Carrega variáveis de ambiente
    load_dotenv()
    
    # Credenciais do Bling
    CLIENT_ID = "48d4b5b7fc8e64fbd1724ce95d97c8a595deea3f"
    CLIENT_SECRET = "df0444306ed1cfbbedf69abf57bc5140ef24277f0e4e5b8070c08dbb4607"
    
    # Função de teste assíncrona
    async def test_token_manager():
        # Inicializa o gerenciador de token
        token_manager = BlingTokenManager(
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET
        )
        
        # Verifica se temos um token válido
        token = await token_manager.get_valid_token()
        
        if token:
            print(f"Token válido: {token[:15]}...")
            
            # Inicia job de renovação para teste
            token_manager.start_renewal_job(interval_hours=5)
            
            # Para demonstração, espera 10 segundos
            print("Job de renovação iniciado, esperando 10 segundos...")
            await asyncio.sleep(10)
            
            # Para o job
            token_manager.stop_renewal_job()
            print("Job de renovação parado")
        else:
            print("Não foi possível obter um token válido")
            
            # Se não temos token, podemos usar um código de autorização para obter
            auth_code = input("Digite um código de autorização (ou deixe em branco para sair): ")
            
            if auth_code:
                success = await token_manager.ensure_token_file_exists(auth_code)
                if success:
                    print("Token criado com sucesso!")
                else:
                    print("Falha ao criar token")
    
    # Executa teste
    asyncio.run(test_token_manager())