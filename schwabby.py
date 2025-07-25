import base64
import hashlib
import os
import requests
import webbrowser
import urllib.parse
import threading
import http.server
import socketserver
import time

class SchwabAuth:
    AUTH_URL = "https://api.schwab.com/oauth/authorize"
    TOKEN_URL = "https://api.schwab.com/oauth/token"
    API_BASE_URL = "https://api.schwab.com"

    def __init__(self, client_id, client_secret, redirect_uri, scopes):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.scopes = scopes
        self.code_verifier = None
        self.access_token = None
        self.refresh_token = None
        self.token_expires_at = 0

    def generate_pkce_pair(self):
        code_verifier = base64.urlsafe_b64encode(os.urandom(40)).rstrip(b'=').decode('utf-8')
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode('utf-8')).digest()
        ).rstrip(b'=').decode('utf-8')
        self.code_verifier = code_verifier
        return code_challenge

    def start_auth_flow(self):
        code_challenge = self.generate_pkce_pair()
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(self.scopes),
            "code_challenge": code_challenge,
            "code_challenge_method": "S256"
        }
        url = f"{self.AUTH_URL}?{urllib.parse.urlencode(params)}"
        print("Opening browser for Schwab login...")
        webbrowser.open(url)

        # Start a simple HTTP server to catch the redirect with the code
        code = self._start_http_server_for_code()
        if not code:
            raise Exception("Failed to get authorization code")
        self.exchange_code_for_token(code)

    def _start_http_server_for_code(self):
        # Parse redirect_uri to get port and path
        parsed = urllib.parse.urlparse(self.redirect_uri)
        port = parsed.port or 80
        path = parsed.path

        code_container = {}

        class AuthHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path.startswith(path):
                    query = urllib.parse.urlparse(self.path).query
                    params = urllib.parse.parse_qs(query)
                    if "code" in params:
                        code_container['code'] = params['code'][0]
                        self.send_response(200)
                        self.send_header('Content-type', 'text/html')
                        self.end_headers()
                        self.wfile.write(b"<html><body><h1>Authentication successful. You can close this window.</h1></body></html>")
                    else:
                        self.send_response(400)
                        self.end_headers()
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, format, *args):
                return  # Suppress logging

        with socketserver.TCPServer(("", port), AuthHandler) as httpd:
            # Run server in a separate thread
            server_thread = threading.Thread(target=httpd.serve_forever)
            server_thread.daemon = True
            server_thread.start()

            # Wait for code or timeout
            for _ in range(300):  # 300 * 0.1 = 30 seconds timeout
                if 'code' in code_container:
                    break
                time.sleep(0.1)

            httpd.shutdown()
            return code_container.get('code')

    def exchange_code_for_token(self, code):
        auth_str = f"{self.client_id}:{self.client_secret}"
        b64_auth_str = base64.b64encode(auth_str.encode()).decode()

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "code_verifier": self.code_verifier
        }
        headers = {
            "Authorization": f"Basic {b64_auth_str}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        response = requests.post(self.TOKEN_URL, data=data, headers=headers)
        if response.status_code != 200:
            raise Exception(f"Token exchange failed: {response.status_code} {response.text}")
        tokens = response.json()
        self.access_token = tokens["access_token"]
        self.refresh_token = tokens.get("refresh_token")
        expires_in = tokens.get("expires_in", 3600)
        self.token_expires_at = time.time() + expires_in - 60  # refresh 1 min early

    def refresh_access_token(self):
        if not self.refresh_token:
            raise Exception("No refresh token available")
        auth_str = f"{self.client_id}:{self.client_secret}"
        b64_auth_str = base64.b64encode(auth_str.encode()).decode()

        data = {
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token
        }
        headers = {
            "Authorization": f"Basic {b64_auth_str}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        response = requests.post(self.TOKEN_URL, data=data, headers=headers)
        if response.status_code != 200:
            raise Exception(f"Refresh token failed: {response.status_code} {response.text}")
        tokens = response.json()
        self.access_token = tokens["access_token"]
        self.refresh_token = tokens.get("refresh_token", self.refresh_token)
        expires_in = tokens.get("expires_in", 3600)
        self.token_expires_at = time.time() + expires_in - 60

    def get_access_token(self):
        if not self.access_token or time.time() > self.token_expires_at:
            self.refresh_access_token()
        return self.access_token

    def api_get(self, endpoint, params=None):
        token = self.get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json"
        }
        url = f"{self.API_BASE_URL}{endpoint}"
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 401:
            # Token might be expired or invalid, try refresh once
            self.refresh_access_token()
            token = self.get_access_token()
            headers["Authorization"] = f"Bearer {token}"
            response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response.json()

# Example usage:
if __name__ == "__main__":
    # Replace these with your actual Schwab app credentials and redirect URI
    CLIENT_ID = "YOUR_CLIENT_ID"
    CLIENT_SECRET = "YOUR_CLIENT_SECRET"
    REDIRECT_URI = "http://localhost:8080/callback"
    SCOPES = ["read_accounts", "read_positions", "read_transactions"]

    auth = SchwabAuth(CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, SCOPES)
    auth.start_auth_flow()

    # Example: get accounts
    accounts = auth.api_get("/accounts/v1/accounts")
    print("Accounts:", accounts)
