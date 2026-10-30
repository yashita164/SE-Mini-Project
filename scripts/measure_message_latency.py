#!/usr/bin/env python3
"""Run a 100-client message latency load test against the local chat server."""

import argparse
import csv
import json
import socket
import sqlite3
import tempfile
import threading
import time
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bcrypt

import auth
import database
import server

PASSWORD = "LatencyTest123!"
TARGET_MS = 500.0


class LatencyClient:
    def __init__(self, address, username):
        self.username = username
        self.sock = socket.create_connection(address, timeout=5)
        self.sock.settimeout(5)
        self.stream = self.sock.makefile("rb")

    def send(self, payload):
        self.sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))

    def receive(self, timeout=5):
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("response timeout")
            self.sock.settimeout(remaining)
            line = self.stream.readline()
            if not line:
                raise ConnectionError("server closed the connection")
            payload = json.loads(line.decode("utf-8"))
            if payload.get("type") == "PING":
                self.send({"type": "PONG"})
                continue
            return payload

    def close(self):
        try:
            self.stream.close()
        finally:
            try:
                self.sock.close()
            except OSError:
                pass


def percentile(values, percentile_value):
    ordered = sorted(values)
    if not ordered:
        return 0.0
    rank = (len(ordered) - 1) * percentile_value / 100.0
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def run_load_test(client_count, samples_per_client):
    if not 1 <= client_count <= 100:
        raise ValueError("client_count must be between 1 and 100")

    temporary_directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    database_path = Path(temporary_directory.name) / "latency.db"
    database.DB_PATH = database_path

    original_gensalt = bcrypt.gensalt
    auth.bcrypt.gensalt = lambda: original_gensalt(rounds=4)

    database.init_db()
    chat_server = server.ChatServer(("127.0.0.1", 0), server.ChatHandler)
    server_thread = threading.Thread(target=chat_server.serve_forever, daemon=True)
    server_thread.start()

    clients = []
    latencies = []
    raw_rows = []

    try:
        address = chat_server.server_address
        for index in range(client_count):
            username = f"latency_user_{index:03d}"
            client = LatencyClient(address, username)
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

        for sample_index in range(samples_per_client):
            for sender_index, sender in enumerate(clients):
                recipient_index = (sender_index + 1) % client_count
                recipient = clients[recipient_index]
                marker = f"latency-{sample_index}-{sender_index}"

                started = time.perf_counter()
                sender.send({
                    "type": "SEND_MESSAGE",
                    "token": sender.token,
                    "toUser": recipient.username,
                    "content": marker,
                })

                delivered = recipient.receive(timeout=5)
                elapsed_ms = (time.perf_counter() - started) * 1000.0

                if delivered.get("type") != "NEW_MESSAGE" or delivered.get("content") != marker:
                    raise RuntimeError(f"unexpected delivery response: {delivered}")

                sender_confirmation = sender.receive(timeout=5)
                if sender_confirmation.get("type") not in {"MESSAGE_DELIVERED", "MESSAGE_STORED"}:
                    raise RuntimeError(f"unexpected sender confirmation: {sender_confirmation}")

                latencies.append(elapsed_ms)
                raw_rows.append({
                    "sample": len(latencies),
                    "sender": sender.username,
                    "recipient": recipient.username,
                    "latency_ms": f"{elapsed_ms:.3f}",
                })

        p95 = percentile(latencies, 95)
        passed = p95 <= TARGET_MS
        return p95, latencies, raw_rows, passed
    finally:
        for client in clients:
            client.close()
        chat_server.shutdown()
        chat_server.server_close()
        server_thread.join(timeout=3)
        auth.bcrypt.gensalt = original_gensalt
        temporary_directory.cleanup()


def write_raw_results(path, raw_rows, client_count, p95_ms, passed):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=["sample", "sender", "recipient", "latency_ms"])
        writer.writeheader()
        writer.writerows(raw_rows)
    metadata = path.with_suffix(".metadata.json")
    metadata.write_text(json.dumps({
        "concurrent_clients": client_count,
        "sample_count": len(raw_rows),
        "p95_latency_ms": round(p95_ms, 3),
        "target_ms": TARGET_MS,
        "result": "PASS" if passed else "FAIL",
    }, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--clients", type=int, default=100)
    parser.add_argument("--samples-per-client", type=int, default=10)
    parser.add_argument("--raw-output", default="docs/performance/tc-perf-01-raw.csv")
    args = parser.parse_args()

    p95, latencies, raw_rows, passed = run_load_test(args.clients, args.samples_per_client)
    write_raw_results(args.raw_output, raw_rows, args.clients, p95, passed)

    print(json.dumps({
        "concurrent_clients": args.clients,
        "sample_count": len(latencies),
        "p95_latency_ms": round(p95, 3),
        "target_ms": TARGET_MS,
        "result": "PASS" if passed else "FAIL",
        "raw_results": args.raw_output,
    }, indent=2))

    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
