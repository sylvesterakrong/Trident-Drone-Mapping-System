import socket
import threading

class TCPListener:
    """
    Listens to PTZ camera TCP commands.
    Calls callback() when a capture command is received.
    """
    def __init__(self, host="0.0.0.0", port=5555, callback=None):
        self.host = host
        self.port = port
        self.callback = callback
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind((host, port))
        self.sock.listen(1)
        print(f"TCP Listener started on {host}:{port}")

    def start(self):
        thread = threading.Thread(target=self._accept_connections, daemon=True)
        thread.start()

    def _accept_connections(self):
        while True:
            conn, addr = self.sock.accept()
            print(f"Connected by {addr}")
            thread = threading.Thread(target=self._handle_client, args=(conn,), daemon=True)
            thread.start()

    def _handle_client(self, conn):
        with conn:
            while True:
                data = conn.recv(1024)
                if not data:
                    break
                command = data.decode().strip()
                # Assuming camera sends "CAPTURE" command
                if command.upper() == "CAPTURE" and self.callback:
                    try:
                        self.callback()
                    except Exception as e:
                        print("Error during capture:", e)