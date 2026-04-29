# CLI Implementation Plan for FocalPointAligner

## Overview

Create a comprehensive CLI interface for FocalPointAligner to enable programmatic testing and batch operations. The core logic in `aligner_core.py` is already UI-independent and ready for CLI wrapping.

## Architecture

```
FocalPointAligner/
├── cli.py                    # NEW: Main CLI entry point
├── aligner_core.py           # EXISTS: Core logic (no changes needed)
├── main.py                   # EXISTS: PyQt6 GUI (unchanged)
├── scripts/
│   └── align_and_scale_images.py  # EXISTS: Batch CLI (keep as-is)
├── ui/                       # EXISTS: PyQt6 UI (unchanged)
├── tests/
│   └── test_cli.py          # NEW: CLI tests
└── requirements.txt           # Add click? (optional)
```

## Implementation Tasks

### Task 1: Create CLI Core Structure (`cli.py`)

**File:** `cli.py`

**Description:**
Create the main CLI entry point using `argparse` with subcommand support.

**Requirements:**
- Use `argparse` (stdlib) for argument parsing
- Support `--json` flag on all commands for programmatic output
- Initialize `FocalPointAlignerCore` from `aligner_core.py`
- Load/save state from `focal_points.json` automatically

**Commands to implement:**
```
focalpoint init --input <path> --output <path> --width 2560 --height 1440
focalpoint status
focalpoint navigate --index <n> | --next | --prev
focalpoint set-focal --x <int> --y <int> [--index <n>]
focalpoint clear-focal [--index <n>]
focalpoint save
focalpoint skip
focalpoint discard [--index <n>]
focalpoint reset [--confirm]
focalpoint export --orientation [landscape|portrait]
focalpoint stats
focalpoint list-images [--with-focal] [--without-focal]
focalpoint get-image --index <n> --type [original|preview] --orientation [landscape|portrait]
```

**Key functions:**
- `main()` - Entry point with argparse setup
- `execute_command(args)` - Route to appropriate command handler
- `cmd_init(core, args)` - Initialize new session
- `cmd_status(core, args)` - Show current status
- `cmd_navigate(core, args)` - Navigate images
- `cmd_set_focal(core, args)` - Set focal point
- `cmd_save(core, args)` - Save and advance
- `cmd_export(core, args)` - Generate final images
- `output_success(data, json_mode)` - Format output
- `output_error(message, json_mode)` - Format errors

---

### Task 2: Implement Core Commands

**File:** `cli.py` (continued)

**Commands to implement in detail:**

#### `init`
- Create `FocalPointAlignerCore` with config dict
- Validate input folder exists and contains images
- Return JSON: `{success: true, total_images: N, message: "..."}`

#### `status`
- Return current state:
  ```json
  {
    "current_index": 0,
    "total_images": 10,
    "completed_count": 3,
    "current_focal": [500, 300] or null,
    "current_filename": "image001.jpg",
    "alignment_mode": "landscape",
    "preview_ready": true
  }
  ```

#### `navigate`
- Support `--index N`, `--next`, `--prev`
- Call `core.navigate_to(idx)` or `core.navigate(direction)`
- Return new index and filename

#### `set-focal`
- Set focal point for current (or specified) image
- Call `core.set_focal_point(x, y)`
- Return confirmation with coordinates

#### `save`
- Call `core.confirm_and_save()`
- Return new current index and stats

#### `export`
- Call `core.set_alignment_mode(orientation)`
- Generate preview if needed
- Copy aligned images to output folder
- Return: `{success: true, exported: N, output_folder: "..."}`

#### `list-images`
- List all images with focal point status
- Filter with `--with-focal` or `--without-focal`
- Output format:
  ```json
  [
    {"index": 0, "filename": "img001.jpg", "has_focal": true, "focal": [500, 300]},
    ...
  ]
  ```

#### `get-image`
- Get image info or save to disk
- Use `--save-to <path>` to write image file
- Support original and preview images
- Return image shape/metadata

---

### Task 3: Add JSON Output Support

**File:** `cli.py`

**Description:**
Add `--json` flag support to all commands for programmatic parsing.

**Implementation:**
```python
def output_success(data, json_mode):
    if json_mode:
        print(json.dumps(data, indent=2))
    else:
        # Human-readable format
        for key, value in data.items():
            print(f"{key}: {value}")

def output_error(message, json_mode):
    if json_mode:
        print(json.dumps({"error": message}, indent=2))
    else:
        print(f"Error: {message}")
```

**Usage:**
```bash
# Human-readable (default)
python cli.py status
# Output: current_index: 0
#          total_images: 10
#          ...

# JSON output for programmatic parsing
python cli.py status --json
# Output: {"current_index": 0, "total_images": 10, ...}
```

---

### Task 4: Add Testing Helper Commands

**File:** `cli.py`

**Description:**
Add commands specifically for testing/verification.

**New commands:**

#### `verify-alignment`
```bash
focalpoint verify-alignment --index 0 --orientation landscape \
  --expected-focal-x 500 --expected-focal-y 300
```
- Load preview image
- Verify focal point was applied correctly
- Return pass/fail with details

#### `batch-set`
```bash
focalpoint batch-set --file focal_points.json
```
Where `focal_points.json` contains:
```json
[
  {"index": 0, "x": 500, "y": 300},
  {"index": 1, "x": 1200, "y": 800},
  ...
]
```

#### `test-run`
```bash
focalpoint test-run --operations operations.json
```
Where `operations.json`:
```json
[
  {"action": "init", "input": "/path/to/images"},
  {"action": "set-focal", "index": 0, "x": 500, "y": 300},
  {"action": "save"},
  {"action": "set-focal", "index": 1, "x": 1200, "y": 800},
  {"action": "save"},
  {"action": "export", "orientation": "landscape"}
]
```

---

### Task 5: Create CLI Tests

**File:** `tests/test_cli.py`

**Description:**
Create comprehensive tests for CLI commands using pytest.

**Test cases:**

```python
import pytest
import subprocess
import json
from pathlib import Path

class TestCLIInit:
    def test_init_valid_folder(self, tmp_path):
        """Test init with valid image folder."""
        # Create test images
        img_dir = tmp_path / "images"
        img_dir.mkdir()
        # ... create dummy images ...
        
        result = subprocess.run(
            ["python", "cli.py", "init", "--input", str(img_dir), "--json"],
            capture_output=True, text=True
        )
        data = json.loads(result.stdout)
        assert data["success"] == True
        assert data["total_images"] > 0

    def test_init_invalid_folder(self):
        """Test init with non-existent folder."""
        result = subprocess.run(
            ["python", "cli.py", "init", "--input", "/nonexistent", "--json"],
            capture_output=True, text=True
        )
        assert "error" in result.stdout.lower() or result.returncode != 0

class TestCLISetFocal:
    def test_set_focal_valid(self, initialized_cli):
        """Test setting a valid focal point."""
        result = subprocess.run(
            ["python", "cli.py", "set-focal", "--index", "0", 
             "--x", "500", "--y", "300", "--json"],
            capture_output=True, text=True
        )
        data = json.loads(result.stdout)
        assert data["focal"] == [500, 300]

class TestCLIExport:
    def test_export_landscape(self, initialized_cli_with_focals):
        """Test exporting aligned images."""
        result = subprocess.run(
            ["python", "cli.py", "export", "--orientation", "landscape", "--json"],
            capture_output=True, text=True
        )
        data = json.loads(result.stdout)
        assert data["success"] == True
        assert data["exported"] > 0
```

**Fixtures:**
```python
@pytest.fixture
def initialized_cli(tmp_path):
    """Initialize CLI with test images."""
    # Setup test environment
    # Return path to initialized directory
    pass

@pytest.fixture
def initialized_cli_with_focals(initialized_cli):
    """Initialize with focal points set."""
    # Set some focal points
    pass
```

---

### Task 6: Update Documentation

**Files:** 
- `README.md` (create if not exists)
- Add CLI section to existing docs

**Content:**
```markdown
## CLI Usage

The FocalPointAligner includes a CLI interface for programmatic testing and batch operations.

### Installation
```bash
pip install -r requirements.txt
```

### Quick Start
```bash
# Initialize with input folder
python cli.py init --input /path/to/images --output /path/to/output

# Check status
python cli.py status

# Set focal point
python cli.py set-focal --index 0 --x 1280 --y 720

# Save and advance
python cli.py save

# Export aligned images
python cli.py export --orientation landscape

# JSON output for scripting
python cli.py status --json | jq '.completed_count'
```

### All Commands
[Full command reference table]
```

---

## Implementation Order

1. **Task 1**: Create `cli.py` with argparse structure ✅ COMPLETED
2. **Task 2**: Implement all core commands ✅ COMPLETED
3. **Task 3**: Add JSON output support ✅ COMPLETED
4. **Task 4**: Add testing helper commands ✅ COMPLETED
5. **Task 5**: Create tests in `tests/test_cli.py` ✅ COMPLETED
6. **Task 6**: Update documentation ✅ COMPLETED

## Completion Summary

### Files Created/Modified:
- ✅ `cli.py` - Main CLI entry point with 13 commands + 3 testing helpers
- ✅ `tests/__init__.py` - Package init
- ✅ `tests/test_cli.py` - Comprehensive pytest tests
- ✅ `README.md` - Updated with CLI documentation
- ✅ `CLI_IMPLEMENTATION_PLAN.md` - This plan file

### Commands Implemented:
| Command | Status |
|---------|--------|
| `init` | ✅ |
| `status` | ✅ |
| `navigate` | ✅ |
| `set-focal` | ✅ |
| `save` | ✅ |
| `skip` | ✅ |
| `clear-focal` | ✅ |
| `discard` | ✅ |
| `reset` | ✅ |
| `export` | ✅ |
| `stats` | ✅ |
| `list-images` | ✅ |
| `get-image` | ✅ |
| `verify-alignment` | ✅ (testing helper) |
| `batch-set` | ✅ (testing helper) |
| `test-run` | ✅ (testing helper) |

### Testing:
- ✅ Test fixtures for temp directories
- ✅ Tests for all commands
- ✅ Error handling tests
- ✅ JSON output tests

### Documentation:
- ✅ README.md with CLI usage
- ✅ Command reference table
- ✅ JSON output examples
- ✅ Testing instructions

---

## Success Criteria

- [ ] All commands implemented and working
- [ ] `--json` flag works on all commands
- [ ] Can initialize, set focal points, save, and export via CLI
- [ ] Tests pass with `pytest`
- [ ] Documentation updated
- [ ] Existing GUI (`main.py`) still works unchanged
- [ ] Existing batch script (`scripts/align_and_scale_images.py`) still works unchanged

---

## Notes

- The `aligner_core.py` file should NOT need modifications
- PyQt6 is NOT required for CLI (core already handles this)
- All state is persisted to `focal_points.json` automatically
- Use `python cli.py <command> --help` for usage details
