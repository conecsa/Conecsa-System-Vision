"""Entrypoint: `python3 -m agent` starts the hardware-management gRPC server."""
from .server import serve

if __name__ == "__main__":
    serve()
