import requests
import json

def fetch_category_attributes():
    url = "https://api.mercadolibre.com/categories/MLB26426/attributes"
    
    try:
        response = requests.get(url)
        response.raise_for_status()  # Levanta exceção para status de erro HTTP
        attributes = response.json()
        print("Atributos da categoria MLB26426:")
        print(json.dumps(attributes, indent=2, ensure_ascii=False))
    except requests.exceptions.HTTPError as http_err:
        print("HTTP error:", http_err)
    except requests.exceptions.ConnectionError as conn_err:
        print("Erro de conexão:", conn_err)
    except requests.exceptions.Timeout as timeout_err:
        print("Timeout error:", timeout_err)
    except requests.exceptions.RequestException as req_err:
        print("Erro na requisição:", req_err)

if __name__ == "__main__":
    fetch_category_attributes()
