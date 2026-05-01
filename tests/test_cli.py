import pytest
import subprocess
import json
import sys
from pathlib import Path
import shutil
import tempfile
import os

PROJECT_DIR = Path(__file__).parent.parent.resolve()

@pytest.fixture
def temp_image_dir(tmp_path):
    """Create a temporary directory with test images."""
    img_dir = tmp_path / "test_images"
    img_dir.mkdir()
    import cv2
    import numpy as np
    for i in range(5):
        img = np.zeros((1080, 1920, 3), dtype=np.uint8)
        cv2.imwrite(str(img_dir / f"image{i:04d}.jpg"), img)
    return img_dir


@pytest.fixture
def initialized_cli(temp_image_dir, tmp_path):
    """Initialize CLI with test images."""
    output_dir = tmp_path / "output"
    # Remove any existing config.json in project dir
    config_file = Path(PROJECT_DIR) / "config.json"
    if config_file.exists():
        config_file.unlink()
    result = subprocess.run(
        [sys.executable, "cli.py", "init", 
         "--input", str(temp_image_dir),
         "--output", str(output_dir),
         "--json"],
        capture_output=True, text=True,
        cwd=PROJECT_DIR
    )
    return temp_image_dir, output_dir, result


class TestCLIInit:
    def test_init_valid_folder(self, temp_image_dir, tmp_path):
        """Test init with valid image folder."""
        output_dir = tmp_path / "output"
        result = subprocess.run(
            [sys.executable, "cli.py", "init", 
             "--input", str(temp_image_dir),
             "--output", str(output_dir),
             "--json"],
            capture_output=True, text=True,
            cwd=PROJECT_DIR
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["total_images"] == 5
    
    def test_init_invalid_folder(self):
        """Test init with non-existent folder."""
        result = subprocess.run(
            [sys.executable, "cli.py", "init", 
             "--input", "/nonexistent",
             "--json"],
            capture_output=True, text=True,
            cwd=PROJECT_DIR
        )
        assert result.returncode != 0


class TestCLISetFocal:
    def test_set_focal_valid(self, initialized_cli):
        """Test setting a valid focal point."""
        temp_image_dir, output_dir, _ = initialized_cli
        result = subprocess.run(
            [sys.executable, "cli.py", "set-focal", 
             "--index", "0", "--x", "500", "--y", "300",
             "--json"],
            capture_output=True, text=True,
            cwd=PROJECT_DIR
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["focal"] == [500, 300]
    
    def test_set_focal_out_of_range(self, initialized_cli):
        """Test setting focal point with invalid index."""
        temp_image_dir, output_dir, _ = initialized_cli
        result = subprocess.run(
            [sys.executable, "cli.py", "set-focal", 
             "--index", "99", "--x", "500", "--y", "300",
             "--json"],
            capture_output=True, text=True,
            cwd=PROJECT_DIR
        )
        assert result.returncode != 0


class TestCLINavigate:
    def test_navigate_next(self, initialized_cli):
        """Test navigating to next image."""
        temp_image_dir, output_dir, _ = initialized_cli
        result = subprocess.run(
            [sys.executable, "cli.py", "navigate", "--next", "--json"],
            capture_output=True, text=True,
            cwd=PROJECT_DIR
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["current_index"] == 1


class TestCLIStatus:
    def test_status_after_init(self, initialized_cli):
        """Test status command returns correct info."""
        temp_image_dir, output_dir, _ = initialized_cli
        result = subprocess.run(
            [sys.executable, "cli.py", "status", "--json"],
            capture_output=True, text=True,
            cwd=PROJECT_DIR
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "current_index" in data
        assert "total_images" in data
        assert data["total_images"] == 5


class TestCLISave:
    def test_save_after_set_focal(self, initialized_cli):
        """Test save command after setting focal point."""
        temp_image_dir, output_dir, _ = initialized_cli
        subprocess.run(
            [sys.executable, "cli.py", "set-focal", 
             "--index", "0", "--x", "500", "--y", "300"],
            capture_output=True, text=True,
            cwd=PROJECT_DIR
        )
        result = subprocess.run(
            [sys.executable, "cli.py", "save", "--json"],
            capture_output=True, text=True,
            cwd=PROJECT_DIR
        )
        assert result.returncode == 0


class TestCLIListImages:
    def test_list_images(self, initialized_cli):
        """Test listing images."""
        temp_image_dir, output_dir, _ = initialized_cli
        result = subprocess.run(
            [sys.executable, "cli.py", "list-images", "--json"],
            capture_output=True, text=True,
            cwd=PROJECT_DIR
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["total"] == 5
        assert len(data["images"]) == 5


class TestCLIClearFocal:
    def test_clear_focal_valid(self, initialized_cli):
        """Test clearing a set focal point."""
        temp_image_dir, output_dir, _ = initialized_cli
        subprocess.run(
            [sys.executable, "cli.py", "set-focal", 
             "--index", "0", "--x", "500", "--y", "300",
             "--json"],
            capture_output=True, text=True,
            cwd=PROJECT_DIR
        )
        result = subprocess.run(
            [sys.executable, "cli.py", "clear-focal", 
             "--index", "0", "--json"],
            capture_output=True, text=True,
            cwd=PROJECT_DIR
        )
        assert result.returncode == 0


class TestCLISkip:
    def test_skip_next(self, initialized_cli):
        """Test skipping current image moves to next."""
        temp_image_dir, output_dir, _ = initialized_cli
        result = subprocess.run(
            [sys.executable, "cli.py", "skip", "--json"],
            capture_output=True, text=True,
            cwd=PROJECT_DIR
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["current_index"] == 1


class TestCLIStats:
    def test_stats_after_init(self, initialized_cli):
        """Test stats command returns correct counts."""
        temp_image_dir, output_dir, _ = initialized_cli
        result = subprocess.run(
            [sys.executable, "cli.py", "stats", "--json"],
            capture_output=True, text=True,
            cwd=PROJECT_DIR
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["total"] == 5


class TestCLIGetImage:
    def test_get_current_image(self, initialized_cli):
        """Test getting current image info."""
        temp_image_dir, output_dir, _ = initialized_cli
        result = subprocess.run(
            [sys.executable, "cli.py", "get-image", 
             "--index", "0", "--json"],
            capture_output=True, text=True,
            cwd=PROJECT_DIR
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "index" in data
        assert data["index"] == 0


class TestCLIErrorHandling:
    def test_command_without_init(self, tmp_path):
        """Test running command without initializing first."""
        result = subprocess.run(
            [sys.executable, "cli.py", "status", "--json"],
            capture_output=True, text=True,
            cwd=str(tmp_path)
        )
        assert result.returncode != 0

    def test_missing_init_args(self):
        """Test init without required --input."""
        result = subprocess.run(
            [sys.executable, "cli.py", "init", "--json"],
            capture_output=True, text=True,
            cwd=PROJECT_DIR
        )
        assert result.returncode != 0
