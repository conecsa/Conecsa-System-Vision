"""gRPC channels + stubs the gateway talks to.

Two peers:
  - inference-service (proto/inference.proto): DetectionControl, ModelControl,
    ManagementControl — the control/telemetry surface for the headless pipeline.
  - os hardware agent (proto/hardware.proto): network / Wi-Fi / GPIO.

The generated ``*_pb2_grpc`` modules do flat ``import inference_pb2`` /
``import hardware_pb2``, so the compiled-proto directory must be importable. The
Dockerfile compiles the protos into ``gateway/proto`` (see Dockerfile.api-gateway).
"""
import logging
import os
import sys

import grpc

logger = logging.getLogger(__name__)

# Make the compiled stubs importable (flat imports inside the generated code).
_PROTO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "proto")
if _PROTO_DIR not in sys.path:
    sys.path.insert(0, _PROTO_DIR)

import inference_pb2 as inf_pb            # noqa: E402
import inference_pb2_grpc as inf_grpc     # noqa: E402
import hardware_pb2 as hw_pb              # noqa: E402
import hardware_pb2_grpc as hw_grpc       # noqa: E402
import training_pb2 as trn_pb             # noqa: E402
import training_pb2_grpc as trn_grpc      # noqa: E402

from .config import settings  # noqa: E402


class Clients:
    """Long-lived gRPC channels + stubs.

    ``grpc.insecure_channel`` connects lazily (no I/O until the first RPC), so
    building the channels at construction time is cheap and lets every peer come
    up in any order — the first call simply blocks/retries until the server is
    reachable.
    """

    def __init__(self) -> None:
        # The 4MB gRPC default is too small for BacklogResponse pages (25
        # records, each with a base64 JPEG frame ≈ 180KB, is ~4.5MB) and left
        # the offline-buffer drain failing forever. The link is local (docker
        # network), so a generous cap is safe.
        inf_channel = grpc.insecure_channel(
            settings.INFERENCE_GRPC_ADDR,
            options=[("grpc.max_receive_message_length", 64 * 1024 * 1024)],
        )
        self.detection = inf_grpc.DetectionControlStub(inf_channel)
        self.model = inf_grpc.ModelControlStub(inf_channel)
        self.management = inf_grpc.ManagementControlStub(inf_channel)
        hw_channel = grpc.insecure_channel(settings.HARDWARE_AGENT_ADDR)
        self.hardware = hw_grpc.HardwareServiceStub(hw_channel)
        trn_channel = grpc.insecure_channel(settings.TRAINING_GRPC_ADDR)
        self.training = trn_grpc.TrainingControlStub(trn_channel)
        self._inf_channel = inf_channel
        self._hw_channel = hw_channel
        self._trn_channel = trn_channel
        logger.info("gRPC channels: inference=%s os=%s training=%s",
                    settings.INFERENCE_GRPC_ADDR, settings.HARDWARE_AGENT_ADDR,
                    settings.TRAINING_GRPC_ADDR)


clients = Clients()

# Re-export the proto modules so route handlers can build request messages.
inf = inf_pb
hw = hw_pb
trn = trn_pb
