import requests
import json
import webbrowser
from urllib.parse import urlparse, parse_qs
import os
from datetime import datetime
from requests.auth import HTTPBasicAuth

# Suas credenciais do Bling
CLIENT_ID = "48d4b5b7fc8e64fbd1724ce95d97c8a595deea3f"
CLIENT_SECRET = "df0444306ed1cfbbedf69abf57bc5140ef24277f0e4e5b8070c08dbb4607"
REDIRECT_URI = "https://530f-45-171-45-13.ngrok-free.app/callback"

# URLs da API Bling
AUTH_URL = "https://www.bling.com.br/Api/v3/oauth/authorize"
TOKEN_URL = "https://www.bling.com.br/Api/v3/oauth/token"

# Escopos necessários
SCOPES = "produtos estoques depositos"

def get_authorization_url():
    """Gera URL para autorização do usuário"""
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "state": "1234",  # Valor arbitrário para proteção CSRF
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES
    }
    
    # Constrói a URL com parâmetros
    query_string = "&".join([f"{k}={v}" for k, v in params.items()])
    auth_url = f"{AUTH_URL}?{query_string}"
    
    return auth_url

def get_token_with_code(authorization_code):
    """Obtém token usando o código de autorização"""
    
    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    payload = {
        "grant_type": "authorization_code",
        "code": authorization_code,
        "redirect_uri": REDIRECT_URI
    }
    
    # Usando autenticação HTTP Basic com client_id e client_secret
    auth = HTTPBasicAuth(CLIENT_ID, CLIENT_SECRET)
    
    response = requests.post(
        TOKEN_URL, 
        data=payload, 
        headers=headers,
        auth=auth
    )
    
    print(f"Status: {response.status_code}")
    print(f"Resposta completa: {response.text}")
    
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Erro ao obter token: {response.status_code}")
        print(response.text)
        return None

def extract_code_from_url(url):
    """Extrai o código de autorização de uma URL completa"""
    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)
    
    if 'code' in query_params:
        return query_params['code'][0]
    return None

def save_token(token_data):
    """Salva os dados do token em arquivos"""
    with open("bling_token.json", "w") as file:
        json.dump(token_data, file, indent=2)
    print("Token salvo em bling_token.json")

    # Também extrai o token de acesso para o .env
    # Verifica se o arquivo existe
    env_exists = os.path.exists(".env")
    
    mode = "a" if env_exists else "w"
    with open(".env", mode) as env_file:
        if not env_exists:
            env_file.write("# Arquivo de variáveis de ambiente\n\n")
        env_file.write(f"\n# Token Bling gerado em {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        env_file.write(f"BLING_API_KEY={token_data['access_token']}\n")
    
    print("Token de acesso adicionado ao arquivo .env")

# Fluxo principal
print("=== Obtenção de Token para API Bling v3 ===\n")

# Passo 1: Obter URL de autorização
auth_url = get_authorization_url()
print("1. Abra esta URL no seu navegador para autorizar o aplicativo:")
print(f"\n{auth_url}\n")

try:
    webbrowser.open(auth_url)
    print("URL aberta automaticamente no navegador.")
except:
    print("Não foi possível abrir automaticamente. Por favor, copie e cole no navegador.")

print("\n2. Após autorizar, você será redirecionado para a URL de callback.")
print("Cole a URL de redirecionamento completa abaixo (ou apenas o código 'code='):")

redirect_input = input("> ").strip()

# Extrair código de autorização
authorization_code = None

if "code=" in redirect_input:
    # Tenta extrair de uma URL completa
    authorization_code = extract_code_from_url(redirect_input)
elif "://" in redirect_input:
    # Tenta extrair de uma URL parcial
    authorization_code = extract_code_from_url(redirect_input)
else:
    # Assume que o usuário colou apenas o código
    authorization_code = redirect_input

if not authorization_code:
    print("\nNão foi possível identificar o código de autorização.")
    print("Por favor, verifique se você copiou a URL completa ou o parâmetro code corretamente.")
    exit(1)

print(f"\nCódigo de autorização identificado: {authorization_code[:10]}...")

# Passo 3: Obter token com o código
print("\n3. Obtendo token de acesso...")
token_data = get_token_with_code(authorization_code)

if token_data:
    print("\n✅ Token obtido com sucesso!")
    print(f"Access Token: {token_data.get('access_token', 'N/A')[:15]}...")
    print(f"Refresh Token: {token_data.get('refresh_token', 'N/A')[:15]}...")
    print(f"Expira em: {token_data.get('expires_in', 'N/A')} segundos")
    
    # Salvar token
    save_token(token_data)
    
    # Testar token
    print("\n4. Testando o token obtido...")
    test_url = "https://api.bling.com.br/v3/produtos"
    test_headers = {
        "Authorization": f"Bearer {token_data['access_token']}",
        "Accept": "application/json"
    }
    
    try:
        test_response = requests.get(test_url, headers=test_headers, params={"limite": 1})
        
        if test_response.status_code == 200:
            test_data = test_response.json()
            print("\n✅ Teste bem-sucedido! O token está funcionando.")
            print(f"Total de produtos: {test_data.get('meta', {}).get('total', 0)}")
            
            if test_data.get("data") and len(test_data["data"]) > 0:
                produto = test_data["data"][0]
                print(f"Primeiro produto: {produto.get('nome')} (SKU: {produto.get('codigo')})")
        else:
            print(f"\n❌ Falha no teste: Código {test_response.status_code}")
            print(f"Resposta: {test_response.text}")
    except Exception as e:
        print(f"\n❌ Erro ao testar token: {str(e)}")
    
    print("\n✅ Processo concluído! Você pode usar o token salvo em .env e bling_token.json")
else:
    print("\n❌ Falha ao obter o token de acesso.")
    print("Verifique os erros acima e tente novamente.")