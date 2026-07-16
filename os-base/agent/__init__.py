"""Conecsa hardware-management agent.

Runs inside the privileged `os` container and owns all host hardware access:
network/Wi-Fi configuration today; GPIO in a later migration. Exposes a gRPC
`HardwareService` (see proto/hardware.proto) consumed by `inference-service`.
"""
