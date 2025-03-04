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
import time

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 代理列表
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

# 线程安全的计数器类
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

# 自定义线程池服务器
class ThreadingTCPServer(socketserver.ThreadingTCPServer):
    daemon_threads = True  # 线程为守护线程，主线程退出时自动清理
    allow_reuse_address = True  # 允许端口重用
    max_connections = 100  # 最大并发连接数
    connection_queue = Queue(maxsize=max_connections)

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
    def authenticate(self):
        auth_header = self.headers.get('Proxy-Authorization')
        if not auth_header or not auth_header.startswith('Basic '):
            logger.warning("Authentication header missing or invalid")
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
            logger.warning("Invalid username or password")
            self.send_auth_required()
            return False
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
            proxy_sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)  # 启用 TCP Keep-Alive
            proxy_sock.settimeout(30)  # 初始连接超时
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
            self.forward_data(client_sock, proxy_sock, timeout=300)  # 5分钟超时
            proxy_sock.close()
        except Exception as e:
            logger.error(f"CONNECT failed: {str(e)}")
            self.send_error(502, f"CONNECT failed: {str(e)}")
            if 'proxy_sock' in locals():
                proxy_sock.close()

    def forward_data(self, client_sock, proxy_sock, timeout):
        """优化长连接转发，使用 select 实现高效 I/O"""
        start_time = time.time()
        sockets = [client_sock, proxy_sock]
        while time.time() - start_time < timeout:
            readable, _, _ = select.select(sockets, [], [], 1.0)  # 1秒超时检查
            for sock in readable:
                try:
                    data = sock.recv(8192)
                    if not data:
                        return  # 连接关闭
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
            # 为 OpenAI API 优化，保持流式响应
            response = requests.request(
                method=method,
                url=self.path,
                headers={k: v for k, v in self.headers.items() if k.lower() != 'proxy-authorization'},
                data=body,
                proxies={"http": proxy_url, "https": proxy_url},
                auth=auth,
                timeout=30,  # 初始超时
                stream=True
            )
            self.send_response(response.status_code)
            for key, value in response.headers.items():
                if key.lower() != 'transfer-encoding':
                    self.send_header(key, value)
            self.end_headers()

            # 处理流式响应，适合 OpenAI API
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    self.wfile.write(chunk)
                    self.wfile.flush()  # 确保实时发送
        except Exception as e:
            logger.error(f"Request failed: {str(e)}")
            self.send_error(500, f"Request failed: {str(e)}")

    def do_GET(self):
        self.do_method('GET')

    def do_POST(self):
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
    
    server = ThreadingTCPServer(("0.0.0.0", PORT), ProxyHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Server shutting down")
        server.server_close()
