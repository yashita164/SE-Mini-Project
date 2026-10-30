#!/usr/bin/env python3
"""Verify that 200 clients can remain connected with active sessions."""

import argparse
import csv
import json
import socket
import tempfile
import threading
import time
import sys
from pathlib import Path

import bcrypt

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import auth
import database
import server

PASSWORD = "ScaleTest123!"


class ScaleClient:
    def __init__(self, address, username):
        self.username = username
        self.token = None
        self.sock = socket.create_connection(address, timeout=10)
        self.sock.settimeout(10)
        self.stream = self.sock.makefile("rb")

    def send(self, payload):
        self.sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))

    def receive(self):
        while True:
            line = self.stream.readline()
            if not line:
                raise ConnectionError(f"connection dropped for {self.username}")
            payload = json.loads(line.decode("utf-8"))
            if payload.get("type") == "PING":
                self.send({"type": "PONG"})
                continue
            return payload

    def close(self):
        try:
            self.stream.close()
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


def run_scale_test(client_count, stability_seconds):
    if not 1 <= client_count <= 200:
        raise ValueError("client_count must be between 1 and 200")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        database.DB_PATH = Path(directory) / "scale.db"
        database.init_db()

        original_gensalt = bcrypt.gensalt
        auth.bcrypt.gensalt = lambda: original_gensalt(rounds=4)

        chat_server = server.ChatServer(("127.0.0.1", 0), server.ChatHandler)
        server_thread = threading.Thread(target=chat_server.serve_forever, daemon=True)
        server_thread.start()
        clients = []

        try:
            for index in range(client_count):
                username = f"scale_user_{index:03d}"
                client = ScaleClient(chat_server.server_address, username)
                clients.append(client)

                client.send({"type": "REGISTER_REQUEST", "username": username, "password": PASSWORD})
                registration = client.receive()
                if registration.get("status") != "OK":
                    raise RuntimeError(f"registration failed for {username}: {registration}")

                client.send({"type": "LOGIN_REQUEST", "username": username, "password": PASSWORD})
                login = client.receive()
                if login.get("status") != "OK":
                    raise RuntimeError(f"login failed for {username}: {login}")
                client.token = login["token"]

            time.sleep(stability_seconds)

            for client in clients:
                client.send({"type": "HISTORY_REQUEST", "token": client.token})
                response = client.receive()
                if response.get("type") != "HISTORY_RESPONSE":
                    raise RuntimeError(f"active session dropped for {client.username}: {response}")

            return {
                "concurrent_clients": client_count,
                "configured_target": 200,
                "stability_seconds": stability_seconds,
                "active_sessions_verified": len(clients),
                "dropped_sessions": 0,
                "result": "PASS",
            }
        finally:
            for client in clients:
                client.close()
            chat_server.shutdown()
            chat_server.server_close()
            server_thread.join(timeout=3)
            auth.bcrypt.gensalt = original_gensalt


def write_results(path, result):
    csv_path = Path(path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=[
            "concurrent_clients", "configured_target", "stability_seconds",
            "active_sessions_verified", "dropped_sessions", "result",
        ])
        writer.writeheader()
        writer.writerow(result)
    csv_path.with_suffix(".metadata.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--clients", type=int, default=200)
    parser.add_argument("--stability-seconds", type=float, default=5.0)
    parser.add_argument("--raw-output", default="docs/performance/tc-scale-01-raw.csv")
    args = parser.parse_args()

    result = run_scale_test(args.clients, args.stability_seconds)
    write_results(args.raw_output, result)
    print(json.dumps({
        **result,
        "raw_results": args.raw_output,
        "metadata": str(Path(args.raw_output).with_suffix(".metadata.json")),
    }, indent=2))


if __name__ == "__main__":
    main()
