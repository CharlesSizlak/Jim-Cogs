#!/usr/bin/env python3
import socket

with socket.socket() as talker:
    talker.connect(("127.0.0.1", 2896))
    talker.send(b"go for pokes")
