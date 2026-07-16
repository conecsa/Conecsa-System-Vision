"""Unit tests for the gateway's camera gate on StatusResponse.

`camera_connected` has explicit presence precisely so a version skew (new
gateway, older inference-service that never sets the field) does not fail
closed and refuse every Start with a 409.
"""
from gateway.controllers.detection import _camera_connected

import inference_pb2 as inf_pb


def test_camera_connected_true_when_producer_reports_a_camera():
    assert _camera_connected(inf_pb.StatusResponse(camera_connected=True)) is True


def test_camera_connected_false_when_producer_reports_no_camera():
    assert _camera_connected(inf_pb.StatusResponse(camera_connected=False)) is False


def test_unset_field_defaults_to_connected():
    # An inference-service that predates the camera gate: the field never lands
    # on the wire. Defaulting to false would block Start until it is upgraded.
    status = inf_pb.StatusResponse(is_running=False)
    assert status.HasField("camera_connected") is False
    assert _camera_connected(status) is True


def test_explicit_false_survives_a_wire_round_trip():
    # Presence must distinguish "set to false" from "absent" across encode/decode.
    encoded = inf_pb.StatusResponse(camera_connected=False).SerializeToString()
    assert _camera_connected(inf_pb.StatusResponse.FromString(encoded)) is False
