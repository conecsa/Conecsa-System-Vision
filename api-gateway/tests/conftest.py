"""Shared pytest import setup for the api-gateway suite.

``gateway.media`` imports the shared ``conecsa_shm`` package (POSIX SHM rings),
which lives under ``os-base`` in the repo — put it on ``sys.path`` so the gateway
modules import on a plain host. The generated proto stubs already live under
``gateway/proto`` and are added to ``sys.path`` by ``gateway.grpc_clients`` itself
(the SHM readers construct lazily, so importing these modules never touches a
live segment).
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, os.pardir, os.pardir))
_OS_BASE = os.path.join(_REPO_ROOT, "os-base")

if os.path.isdir(_OS_BASE) and _OS_BASE not in sys.path:
    sys.path.insert(0, _OS_BASE)
