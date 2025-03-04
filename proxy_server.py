import http.server
import socketserver
import requests
from requests.auth import HTTPProxyAuth
import threading
import socket
import select
import base64
import os
import logging
from queue import Queue

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

PROXY_LIST = [
    "gZJpExeS:rrD520glAQpqNlko@proxy.proxy302.com:2222",
    "XcjTsSKz:wpRzDh0Vd5dNUYK5@proxy.proxy302.com:2222",
    "K2sg5tWU:hfdIzpnb4UVKPNsh@proxy.proxy302.com:2222",
    "EyDW93ou:RsrEMotgsEEpoKWq@proxy.proxy302.com:2222",
    "vOBgycMK:Yv76aGGpH48CkQxd@proxy.proxy302.com:2222",
    "DgxYcy6A:RQ18c1BDdSlTNYRt@proxy.proxy302.com:2222",
    "o6Ta1Y1D:MXv3ROFVnUybzrCR@proxy.proxy302.com:2222",
    "haxDkXjk:nkLg9tKqVdWrsZWZ@proxy.proxy302.com:2222",
    "7HPJodRF:dTpDBcmsDe4eHBhn@proxy.proxy302.com:2222",
    "N1NEekds:eGRnjoinXgtpVv5G@proxy.proxy302.com:2222"
]

class ThreadSafeCounter:
    def __init__(self):
        self.lock = threading.Lock()
        self.value = 0

    def increment(self):
        with self.lock:
            self.value = (self.value + 1) % len(PROXY_LIST)

    def get_value(self):
        with self.lock:
            return self.value

counter = ThreadSafeCounter()
USERNAME = "QDd8hvwOihuT"
PASSWORD = "IoxUZXJIe7lrEYkb"

class ThreadingTCPServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True
    max_connections = 100

    def __init__(self, server_address, RequestHandlerClass):
        super().__init__(server_address, RequestHandlerClass)
        self.active_connections = 0
        self.lock = threading.Lock()

    def verify_request(self, request, client_address):
        with self.lock:
            if self.active_connections >= self.max_connections:
                logger.warning(f"Max connections ({self.max_connections}) reached, rejecting request")
                return False
            self.active_connections += 1
            return True

    def finish_request(self, request, client_address):
        super().finish_request(request, client_address)
        with self.lock:
            self.active_connections -= 1

class ProxyHandler(http.server.BaseHTTPRequestHandler):
    def handle(self):
        logger.info(f"Received raw connection from {self.client_address}")
        super().handle()

    def authenticate(self):
        if self.client_address[0] == '127.0.0.1':
            logger.info(f"Ignoring health check from {self.client_address}")
            self.send_response(200)
            self.end_headers()
            return False
        auth_header = self.headers.get('Proxy-Authorization')
        if not auth_header or not auth_header.startswith('Basic '):
            logger.warning(f"Authentication header missing or invalid from {self.client_address}")
            self.send_auth_required()
            return False
        encoded_credentials = auth_header.split(' ')[1]
        try:
            decoded_credentials = base64.b64decode(encoded_credentials).decode('utf-8')
            username, password = decoded_credentials.split(':', 1)
        except Exception as e:
            logger.error(f"Failed to decode credentials: {str(e)}")
            self.send_auth_required()
            return False
        if username != USERNAME or password != PASSWORD:
            logger.warning(f"Invalid username or password from {self.client_address}")
            self.send_auth_required()
            return False
        logger.info(f"Authentication successful for {self.client_address}")
        return True

    def send_auth_required(self):
        self.send_response(407)
        self.send_header('Proxy-Authenticate', 'Basic realm="Proxy"')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_CONNECT(self):
        if not self.authenticate():
            return
        proxy = PROXY_LIST[counter.get_value()]
        counter.increment()
        username, rest = proxy.split(':', 1)
        password, proxy_addr = rest.split('@', 1)
        proxy_host, proxy_port = proxy_addr.split(':')
        proxy_port = int(proxy_port)
        dest_host, dest_port = self.path.split(':')
        dest_port = int(dest_port)
        logger.info(f"Handling CONNECT request to {self.path} via proxy {proxy_addr}")
        try:
            proxy_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            proxy_sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            proxy_sock.settimeout(30)
            proxy_sock.connect((proxy_host, proxy_port))
            auth = f"{username}:{password}".encode()
            auth_header = b"Proxy-Authorization: Basic " + base64.b64encode(auth) + b"\r\n"
            connect_req = f"CONNECT {self.path} HTTP/1.1\r\nHost: {self.path}\r\n{auth_header.decode()}\r\n".encode()
            proxy_sock.sendall(connect_req)
            response = proxy_sock.recv(4096)
            if b"200" not in response:
                logger.error(f"Proxy connection failed: {response.decode('utf-8', errors='ignore')}")
                self.send_error(502, "Proxy connection failed")
                proxy_sock.close()
                return
            self.send_response(200, "Connection established")
            self.end_headers()
            client_sock = self.connection
            self.forward_data(client_sock, proxy_sock, timeout=300)
            proxy_sock.close()
        except Exception as e:
            logger.error(f"CONNECT failed: {str(e)}")
            self.send_error(502, f"CONNECT failed: {str(e)}")
            if 'proxy_sock' in locals():
                proxy_sock.close()

    def forward_data(self, client_sock, proxy_sock, timeout):
        start_time = time.time()
        sockets = [client_sock, proxy_sock]
        while time.time() - start_time < timeout:
            readable, _, _ = select.select(sockets, [], [], 1.0)
            for sock in readable:
                try:
                    data = sock.recv(8192)
                    if not data:
                        return
                    if sock is client_sock:
                        proxy_sock.sendall(data)
                    else:
                        client_sock.sendall(data)
                except Exception as e:
                    logger.error(f"Forwarding error: {str(e)}")
                    return
        logger.info("Long connection timed out")

    def do_method(self, method):
        if not self.authenticate():
            return
        logger.info(f"Processing {method} request from {self.client_address}")
        proxy = PROXY_LIST[counter.get_value()]
        counter.increment()
        username, rest = proxy.split(':', 1)
        password, proxy_addr = rest.split('@', 1)
        proxy_url = f"http://{proxy_addr}"
        auth = HTTPProxyAuth(username, password)
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length) if content_length > 0 else None
        logger.info(f"Handling {method} request to {self.path} via proxy {proxy_addr}")
        try:
            response = requests.request(
                method=method,
                url=self.path,
                headers={k: v for k, v in self.headers.items() if k.lower() != 'proxy-authorization'},
                data=body,
                proxies={"http": proxy_url, "https": proxy_url},
                auth=auth,
                timeout=(10, 30),
                stream=True
            )
            self.send_response(response.status_code)
            for key, value in response.headers.items():
                if key.lower() != 'transfer-encoding':
                    self.send_header(key, value)
            self.end_headers()
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    self.wfile.write(chunk)
                    self.wfile.flush()
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {str(e)}")
            self.send_error(502, f"Proxy backend failed: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            self.send_error(500, f"Request failed: {str(e)}")

    def do_GET(self):
        logger.info(f"Received GET request from {self.client_address} for {self.path}")
        self.do_method('GET')

    def do_POST(self):
        logger.info(f"Received POST request from {self.client_address} for {self.path}")
        self.do_method('POST')

    def do_PUT(self):
        self.do_method('PUT')

    def do_DELETE(self):
        self.do_method('DELETE')

    def do_HEAD(self):
        self.do_method('HEAD')

    def do_OPTIONS(self):
        self.do_method('OPTIONS')

    def do_PATCH(self):
        self.do_method('PATCH')

if __name__ == "__main__":
    PORT = int(os.getenv("PORT", 10000))
    logger.info(f"Starting proxy server on port {PORT}")
    logger.info(f"Proxy username: {USERNAME}")
    logger.info(f"Proxy password: {PASSWORD}")
    test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    test_sock.settimeout(10)
    result = test_sock.connect_ex(('proxy.proxy302.com', 2222))
    logger.info(f"External proxy connectivity test: {result}")
    test_sock.close()
    server = ThreadingTCPServer(("0.0.0.0", PORT), ProxyHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Server shutting down")
        server.server_close()
