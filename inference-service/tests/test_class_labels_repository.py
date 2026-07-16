"""Unit tests for ClassLabelsRepository file persistence."""
from api.repositories.class_labels_repository import ClassLabelsRepository


class TestLoadLabels:
    def test_missing_file_returns_empty(self, tmp_path):
        repo = ClassLabelsRepository(str(tmp_path / "classes.txt"))
        assert repo.load_labels() == []

    def test_loads_non_empty_stripped_lines(self, tmp_path):
        f = tmp_path / "classes.txt"
        f.write_text("cat\n\n  dog \nbird\n")
        repo = ClassLabelsRepository(str(f))
        assert repo.load_labels() == ["cat", "dog", "bird"]


class TestSaveLabels:
    def test_save_then_load_roundtrip(self, tmp_path):
        f = tmp_path / "classes.txt"
        repo = ClassLabelsRepository(str(f))
        assert repo.save_labels(["a", "b", "c"]) is True
        assert repo.load_labels() == ["a", "b", "c"]

    def test_save_creates_missing_directory(self, tmp_path):
        f = tmp_path / "nested" / "sub" / "classes.txt"
        repo = ClassLabelsRepository(str(f))
        assert repo.save_labels(["x"]) is True
        assert f.exists()

    def test_save_empty_list(self, tmp_path):
        f = tmp_path / "classes.txt"
        repo = ClassLabelsRepository(str(f))
        assert repo.save_labels([]) is True
        assert repo.load_labels() == []
