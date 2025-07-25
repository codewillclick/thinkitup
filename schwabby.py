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
import tempfile
import ipaddress
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import datetime

def generate_temp_key_cert():
    # Generate private key
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    # Build certificate subject and issuer (self-signed)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, u"127.0.0.1"),
    ])

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow() - datetime.timedelta(days=1))
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName(u"localhost"),
                x509.IPAddress(ipaddress.IPv4Address("127.0.0.1"))
            ]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    # Write key and cert to temp files
    key_file = tempfile.NamedTemporaryFile(delete=False)
    cert_file = tempfile.NamedTemporaryFile(delete=False)

    key_file.write(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    key_file.flush()

    cert_file.write(
        cert.public_bytes(serialization.Encoding.PEM)
    )
    cert_file.flush()

    return key_file.name, cert_file.name

class OAuth2Base:
    """
    Abstract base class for OAuth2 authentication flows.
    Handles common OAuth2 steps: PKCE generation, token exchange, refresh, and API calls.
    """

    AUTH_URL = None
    TOKEN_URL = None
    API_BASE_URL = None

    def __init__(self, client_id, client_secret, redirect_uri, scopes):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.scopes = scopes
        self.code_verifier = None
        self.access_token = None
        self.refresh_token = None
        self.token_expires_at = 0
        self._temp_cert_file = None
        self._temp_key_file = None

    def generate_pkce_pair(self):
        code_verifier = base64.urlsafe_b64encode(os.urandom(40)).rstrip(b'=').decode('utf-8')
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode('utf-8')).digest()
        ).rstrip(b'=').decode('utf-8')
        self.code_verifier = code_verifier
        return code_challenge

    def _generate_temp_selfsigned_cert(self):
        key_file, cert_file = generate_temp_key_cert()
        self._temp_key_file = key_file
        self._temp_cert_file = cert_file

    def _cleanup_temp_cert_files(self):
        try:
            if self._temp_cert_file and os.path.exists(self._temp_cert_file):
                os.remove(self._temp_cert_file)
            if self._temp_key_file and os.path.exists(self._temp_key_file):
                os.remove(self._temp_key_file)
        except Exception:
            pass

    def start_auth_flow(self):
        """
        Starts the OAuth2 authorization flow.
        Opens the browser to the authorization URL and waits for the authorization code.
        """
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
        print(f"Opening browser for login at: {url}")
        webbrowser.open(url)

        # Determine if HTTPS is needed based on redirect_uri scheme
        use_https = urllib.parse.urlparse(self.redirect_uri).scheme == "https"

        certfile = None
        keyfile = None
        if use_https:
            # Generate temp cert/key files if not provided
            self._generate_temp_selfsigned_cert()
            certfile = self._temp_cert_file
            keyfile = self._temp_key_file

        try:
            code = self._start_http_server_for_code(use_https=use_https, certfile=certfile, keyfile=keyfile)
        finally:
            if use_https:
                self._cleanup_temp_cert_files()

        if not code:
            raise Exception("Failed to get authorization code")
        self.exchange_code_for_token(code)

    def _start_http_server_for_code(self, use_https=False, certfile=None, keyfile=None):
        parsed = urllib.parse.urlparse(self.redirect_uri)
        port = parsed.port or (443 if use_https else 80)
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

        if use_https:
            import ssl
            with socketserver.TCPServer(("", port), AuthHandler) as httpd:
                httpd.socket = ssl.wrap_socket(httpd.socket,
                                               server_side=True,
                                               certfile=certfile,
                                               keyfile=keyfile,
                                               ssl_version=ssl.PROTOCOL_TLS)
                server_thread = threading.Thread(target=httpd.serve_forever)
                server_thread.daemon = True
                server_thread.start()

                for _ in range(300):  # 30 seconds timeout
                    if 'code' in code_container:
                        break
                    time.sleep(0.1)

                httpd.shutdown()
                return code_container.get('code')
        else:
            with socketserver.TCPServer(("", port), AuthHandler) as httpd:
                server_thread = threading.Thread(target=httpd.serve_forever)
                server_thread.daemon = True
                server_thread.start()

                for _ in range(300):  # 30 seconds timeout
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
        self.token_expires_at = time.time() + expires_in - 60

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
            self.refresh_access_token()
            token = self.get_access_token()
            headers["Authorization"] = f"Bearer {token}"
            response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response.json()

class SchwabAuth(OAuth2Base):
    AUTH_URL = "https://api.schwab.com/oauth/authorize"
    TOKEN_URL = "https://api.schwab.com/oauth/token"
    API_BASE_URL = "https://api.schwab.com"

    def __init__(self, client_id, client_secret, redirect_uri, scopes):
        super().__init__(client_id, client_secret, redirect_uri, scopes)
        # Additional Schwab-specific initialization if needed

    # Override or add methods if Schwab requires special handling
    # For example, account number hashing or alternative auth steps

# Example usage:
if __name__ == "__main__":
    import os
    import sys
    import ssl
    import socket

    CLIENT_ID = os.getenv("SCHWAB_CLIENT_ID")
    CLIENT_SECRET = os.getenv("SCHWAB_CLIENT_SECRET")
    REDIRECT_URI = "https://127.0.0.1"
    SCOPES = ["read_accounts", "read_positions", "read_transactions"]

    def test_https_server(certfile=None, keyfile=None, port=443):
        import http.server
        import socketserver
        import threading
        import ssl

        class SimpleHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"HTTPS server is working")

            def log_message(self, format, *args):
                return

        if certfile is None or keyfile is None:
            # Generate temp cert/key for test
            keyfile, certfile = generate_temp_key_cert()

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile=certfile, keyfile=keyfile)

        with socketserver.TCPServer(("", port), SimpleHandler) as httpd:
            httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
            print(f"Serving HTTPS on port {port} with cert {certfile} and key {keyfile}")
            server_thread = threading.Thread(target=httpd.serve_forever)
            server_thread.daemon = True
            server_thread.start()

            try:
                # Test connection to server
                client_context = ssl._create_unverified_context()
                with socket.create_connection(("127.0.0.1", port)) as sock:
                    with client_context.wrap_socket(sock, server_hostname="127.0.0.1") as ssock:
                        ssock.sendall(b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
                        data = ssock.recv(1024)
                        print("Received from server:", data.decode())
            except Exception as e:
                print("HTTPS server test failed:", e)
                return False

            httpd.shutdown()

            # Clean up temp files if generated
            if certfile and certfile.startswith(tempfile.gettempdir()):
                try:
                    os.remove(certfile)
                except Exception:
                    pass
            if keyfile and keyfile.startswith(tempfile.gettempdir()):
                try:
                    os.remove(keyfile)
                except Exception:
                    pass

            return True

    if "-c" in sys.argv:
        success = test_https_server()
        if success:
            print("HTTPS server test succeeded")
        else:
            print("HTTPS server test failed")
        sys.exit(0)

    if not CLIENT_ID or not CLIENT_SECRET:
        raise Exception("Environment variables SCHWAB_CLIENT_ID and SCHWAB_CLIENT_SECRET must be set")

    auth = SchwabAuth(CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, SCOPES)
    auth.start_auth_flow()

    # Example: get accounts
    accounts = auth.api_get("/accounts/v1/accounts")
    print("Accounts:", accounts)
