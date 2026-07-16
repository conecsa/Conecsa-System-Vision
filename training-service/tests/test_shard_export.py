"""Unit tests for the deterministic IID shard export (federated training)."""
import json
import zipfile

import pytest

from service.dataset_service import Box, DatasetService

_DATASET_ID = "0123abcd-4567-89ab-cdef-000000000000"


@pytest.fixture
def ds(tmp_path):
    service = DatasetService(_DATASET_ID, str(tmp_path), config=None)
    (tmp_path / "classes.json").write_text(json.dumps(["cap", "bottle"]))
    for i in range(10):
        entry = service.add_image(f"jpeg-{i}".encode())
        # Label every other image so shards mix labeled and unlabeled.
        if i % 2 == 0:
            service.set_labels(entry.image_id, [Box(0, 0.5, 0.5, 0.2, 0.2)])
    return service


def _shard_images(ds, tmp_path, num_shards, index, seed):
    dest = str(tmp_path / f"shard-{index}.zip")
    ds.export_zip(dest, num_shards=num_shards, shard_index=index, seed=seed)
    with zipfile.ZipFile(dest) as zf:
        return {n for n in zf.namelist() if n.startswith("images/")}, dest


class TestShardExport:
    def test_shards_partition_the_dataset(self, ds, tmp_path):
        shards = [_shard_images(ds, tmp_path, 3, i, "seed")[0] for i in range(3)]
        union = set().union(*shards)
        full = {f"images/{e.image_id}.jpg" for e in ds.list_images()}
        assert union == full
        for i in range(3):
            for j in range(i + 1, 3):
                assert not shards[i] & shards[j], "shards must be disjoint"

    def test_shard_sizes_differ_by_at_most_one(self, ds, tmp_path):
        sizes = [len(_shard_images(ds, tmp_path, 3, i, "seed")[0]) for i in range(3)]
        assert max(sizes) - min(sizes) <= 1

    def test_same_seed_is_deterministic(self, ds, tmp_path):
        first, _ = _shard_images(ds, tmp_path, 4, 1, "seed-a")
        again, _ = _shard_images(ds, tmp_path, 4, 1, "seed-a")
        assert first == again

    def test_different_seed_reshuffles(self, ds, tmp_path):
        a = [_shard_images(ds, tmp_path, 2, i, "seed-a")[0] for i in range(2)]
        b = [_shard_images(ds, tmp_path, 2, i, "seed-b")[0] for i in range(2)]
        # Both are valid partitions; with 10 images two seeds virtually never
        # produce the same assignment for shard 0.
        assert a[0] != b[0]

    def test_shard_yaml_keeps_full_class_list(self, ds, tmp_path):
        _, dest = _shard_images(ds, tmp_path, 3, 0, "seed")
        with zipfile.ZipFile(dest) as zf:
            yaml = zf.read("data.yaml").decode()
        assert "nc: 2" in yaml
        assert "'cap', 'bottle'" in yaml

    def test_full_export_unchanged_without_shards(self, ds, tmp_path):
        dest = str(tmp_path / "full.zip")
        count = ds.export_zip(dest)
        assert count == 10
        with zipfile.ZipFile(dest) as zf:
            images = [n for n in zf.namelist() if n.startswith("images/")]
        assert len(images) == 10
