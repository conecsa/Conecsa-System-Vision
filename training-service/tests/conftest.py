"""Shared pytest import setup for the training-service suite.

``service.dataset_import`` pulls in ``service.capture_service``, which imports
the shared ``conecsa_shm`` package (SHM camera ring). That package lives under
``os-base`` in the repo — put it on ``sys.path`` so the pure dataset/label logic
is importable on a plain host. The generated proto stubs (under
``api-gateway/gateway/proto``) are added too for the proto-adjacent modules.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, os.pardir, os.pardir))
_OS_BASE = os.path.join(_REPO_ROOT, "os-base")
_PROTO_DIR = os.path.join(_REPO_ROOT, "api-gateway", "gateway", "proto")

for _path in (_OS_BASE, _PROTO_DIR):
    if os.path.isdir(_path) and _path not in sys.path:
        sys.path.insert(0, _path)
