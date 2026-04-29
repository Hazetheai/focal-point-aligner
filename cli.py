#!/usr/bin/env python3
"""
CLI interface for FocalPointAligner.
Provides command-line interface for managing focal points and exporting aligned images.
"""

import argparse
import json
import sys
import subprocess
from pathlib import Path

from aligner_core import FocalPointAlignerCore


def output_success(data, json_mode=False):
    """Print success data in appropriate format."""
    if json_mode:
        print(json.dumps(data, indent=2))
    else:
        for key, value in data.items():
            print(f"{key}: {value}")


def output_error(message, json_mode=False):
    """Print error message in appropriate format."""
    if json_mode:
        print(json.dumps({"error": message}, indent=2))
    else:
        print(f"Error: {message}", file=sys.stderr)


def load_core_from_config():
    """Try to load existing core from saved config in working directory."""
    config_path = Path("config.json")
    if not config_path.exists():
        return None
    with open(config_path, 'r') as f:
        config = json.load(f)
    input_folder = config.get("input_folder")
    if not input_folder or not Path(input_folder).exists():
        return None
    try:
        return FocalPointAlignerCore(config)
    except Exception:
        return None


def cmd_init(args):
    """Initialize with input folder."""
    input_path = Path(args.input)
    if not input_path.exists():
        output_error(f"Input folder does not exist: {input_path}", args.json)
        return 1

    config = {
        "input_folder": str(input_path.resolve()),
        "target_width": args.width,
        "target_height": args.height,
    }
    
    if args.output:
        config["output_folder"] = str(Path(args.output).resolve())

    config_path = Path("config.json")
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)

    try:
        core = FocalPointAlignerCore(config)
    except Exception as e:
        output_error(str(e), args.json)
        return 1

    output_success({
        "message": "Initialized successfully",
        "input_folder": str(core.input_folder),
        "output_folder": str(core.output_folder),
        "total_images": core.total_images,
        "invalid_images": len(core.invalid_images) if hasattr(core, 'invalid_images') else 0,
        "target_width": core.target_width,
        "target_height": core.target_height,
    }, args.json)
    
    if args.gui:
        main_script = Path(__file__).parent / "main.py"
        subprocess.call([sys.executable, str(main_script), '--config', 'config.json'])
    
    return 0


def cmd_status(args):
    """Show current status."""
    core = load_core_from_config()
    if core is None:
        output_error("No project initialized. Run 'init' first.", args.json)
        return 1

    current_focal = core.get_current_focal()
    status = {
        "current_index": core.current_idx,
        "total_images": core.total_images,
        "completed_count": core.completed_count,
        "current_focal": list(current_focal) if current_focal else None,
        "current_filename": core.image_files[core.current_idx].name if core.image_files and core.current_idx < len(core.image_files) else None,
        "alignment_mode": core.alignment_mode,
    }

    if args.json:
        output_success(status, True)
    else:
        print(f"Index: {status['current_index'] + 1}/{status['total_images']}")
        print(f"Completed: {status['completed_count']}/{status['total_images']}")
        print(f"Focal: {status['current_focal']}")
        print(f"File: {status['current_filename']}")
        print(f"Mode: {status['alignment_mode']}")
    return 0


def cmd_navigate(args):
    """Navigate images."""
    core = load_core_from_config()
    if core is None:
        output_error("No project initialized. Run 'init' first.", args.json)
        return 1

    if args.index is not None:
        idx = args.index
        if idx < 0 or idx >= core.total_images:
            output_error(f"Index out of range (0-{core.total_images - 1})", args.json)
            return 1
        core.navigate_to(idx)
    elif args.next:
        if not core.navigate(1):
            output_error("Already at last image", args.json)
            return 1
    elif args.prev:
        if not core.navigate(-1):
            output_error("Already at first image", args.json)
            return 1

    output_success({
        "current_index": core.current_idx,
        "filename": core.image_files[core.current_idx].name if core.image_files else None,
    }, args.json)
    return 0


def cmd_set_focal(args):
    """Set focal point."""
    core = load_core_from_config()
    if core is None:
        output_error("No project initialized. Run 'init' first.", args.json)
        return 1

    idx = args.index if args.index is not None else core.current_idx

    if idx < 0 or idx >= core.total_images:
        output_error(f"Index out of range (0-{core.total_images - 1})", args.json)
        return 1

    old_idx = core.current_idx
    core.navigate_to(idx)
    core.set_focal_point(args.x, args.y)
    core.save_focal_points()
    core.navigate_to(old_idx)

    output_success({
        "message": f"Focal point set at ({args.x}, {args.y})",
        "index": idx,
        "focal": [args.x, args.y],
    }, args.json)
    return 0


def cmd_save(args):
    """Save current focal point and advance."""
    core = load_core_from_config()
    if core is None:
        output_error("No project initialized. Run 'init' first.", args.json)
        return 1

    saved_idx = core.current_idx
    core.confirm_and_save()

    output_success({
        "message": f"Saved image {saved_idx}",
        "next_index": core.current_idx,
    }, args.json)
    return 0


def cmd_skip(args):
    """Skip to next image without saving."""
    core = load_core_from_config()
    if core is None:
        output_error("No project initialized. Run 'init' first.", args.json)
        return 1

    old_idx = core.current_idx
    if not core.navigate(1):
        output_error("Already at last image", args.json)
        return 1

    output_success({
        "message": f"Skipped from {old_idx} to {core.current_idx}",
        "current_index": core.current_idx,
    }, args.json)
    return 0


def cmd_clear_focal(args):
    """Clear focal point for current or specified image."""
    core = load_core_from_config()
    if core is None:
        output_error("No project initialized. Run 'init' first.", args.json)
        return 1

    idx = args.index if args.index is not None else core.current_idx

    if idx < 0 or idx >= core.total_images:
        output_error(f"Index out of range (0-{core.total_images - 1})", args.json)
        return 1

    old_idx = core.current_idx
    core.navigate_to(idx)
    core.clear_focal_point()
    core.navigate_to(old_idx)

    output_success({
        "message": f"Cleared focal point for image {idx}",
        "index": idx,
    }, args.json)
    return 0


def cmd_discard(args):
    """Discard current image."""
    core = load_core_from_config()
    if core is None:
        output_error("No project initialized. Run 'init' first.", args.json)
        return 1

    idx = args.index if args.index is not None else core.current_idx

    if idx < 0 or idx >= core.total_images:
        output_error(f"Index out of range (0-{core.total_images - 1})", args.json)
        return 1

    old_idx = core.current_idx
    core.navigate_to(idx)
    core.discard_current()
    core.navigate_to(old_idx)

    output_success({
        "message": f"Discarded image at index {idx}",
        "remaining_images": core.total_images,
    }, args.json)
    return 0


def cmd_reset(args):
    """Reset all focal points."""
    core = load_core_from_config()
    if core is None:
        output_error("No project initialized. Run 'init' first.", args.json)
        return 1

    if not args.confirm:
        response = input("This will delete all focal points and previews. Continue? [y/N]: ")
        if response.lower() != 'y':
            print("Cancelled.")
            return 0

    core.reset_all()

    config_path = Path("config.json")
    if config_path.exists():
        config_path.unlink()

    output_success({
        "message": "Reset all focal points and previews",
    }, args.json)
    return 0


def cmd_export(args):
    """Export aligned images."""
    core = load_core_from_config()
    if core is None:
        output_error("No project initialized. Run 'init' first.", args.json)
        return 1

    orientation = args.orientation or core.alignment_mode or "landscape"
    core.set_alignment_mode(orientation)

    core.prepare_aligned_previews(orientation)

    folder = core.get_preview_folder(orientation)
    count = core.get_preview_image_count(orientation)

    output_success({
        "message": f"Exported {count} images in {orientation} orientation",
        "output_folder": str(folder),
        "orientation": orientation,
    }, args.json)
    return 0


def cmd_stats(args):
    """Show progress statistics."""
    core = load_core_from_config()
    if core is None:
        output_error("No project initialized. Run 'init' first.", args.json)
        return 1

    stats = core.get_stats()

    if args.json:
        output_success(stats, True)
    else:
        print(f"Total images: {stats['total']}")
        print(f"With focal points: {stats['with_focal']}")
        print(f"Center-auto: {stats['center_focal']}")
        print(f"Without focal: {stats['without_focal']}")
        print(f"Input folder: {stats['input_folder']}")
    return 0


def cmd_list_images(args):
    """List images with focal point status."""
    core = load_core_from_config()
    if core is None:
        output_error("No project initialized. Run 'init' first.", args.json)
        return 1

    images = []
    for idx, img_file in enumerate(core.image_files):
        focal = core.focal_points.get(idx)
        status = "completed" if focal else "pending"
        if args.with_focal and not focal:
            continue
        if args.without_focal and focal:
            continue
        images.append({
            "index": idx,
            "filename": img_file.name,
            "focal": list(focal) if focal else None,
            "status": status,
        })

    output_success({
        "images": images,
        "total": len(images),
    }, args.json)
    return 0


def cmd_get_image(args):
    """Get image info or save to disk."""
    import shutil

    core = load_core_from_config()
    if core is None:
        output_error("No project initialized. Run 'init' first.", args.json)
        return 1

    idx = args.index
    if idx < 0 or idx >= core.total_images:
        output_error(f"Index out of range (0-{core.total_images - 1})", args.json)
        return 1

    orientation = args.orientation or core.alignment_mode or "landscape"

    if args.type == "original":
        img_file = core.image_files[idx]
        if args.save_to:
            dest = Path(args.save_to)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(img_file, dest)
            output_success({
                "message": f"Copied original image to {dest}",
                "source": str(img_file),
                "destination": str(dest),
            }, args.json)
        else:
            dims = core.image_dimensions.get(idx)
            focal = core.focal_points.get(idx)
            output_success({
                "index": idx,
                "filename": img_file.name,
                "dimensions": dims,
                "focal": list(focal) if focal else None,
            }, args.json)
    else:
        core.navigate_to(idx)
        img = core.ensure_preview_for_current(orientation)
        folder = core.get_preview_folder(orientation)
        preview_path = folder / f"{idx:04d}.jpg"

        if args.save_to:
            dest = Path(args.save_to)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(preview_path, dest)
            output_success({
                "message": f"Copied preview to {dest}",
                "source": str(preview_path),
                "destination": str(dest),
            }, args.json)
        else:
            output_success({
                "index": idx,
                "preview_path": str(preview_path),
                "orientation": orientation,
            }, args.json)
    return 0


def cmd_verify_alignment(args):
    """Verify focal point alignment for an image."""
    core = load_core_from_config()
    if core is None:
        output_error("No project initialized. Run 'init' first.", args.json)
        return 1

    idx = args.index
    if idx < 0 or idx >= core.total_images:
        output_error(f"Index out of range (0-{core.total_images - 1})", args.json)
        return 1

    orientation = args.orientation or core.alignment_mode or "landscape"
    core.navigate_to(idx)

    # Get the preview image
    preview = core.get_preview_image(orientation)
    if preview is None:
        output_error(f"No preview found for image {idx}", args.json)
        return 1

    focal = core.focal_points.get(idx)
    result = {
        "index": idx,
        "orientation": orientation,
        "has_focal": focal is not None,
        "focal": list(focal) if focal else None,
    }

    if args.expected_focal_x is not None and args.expected_focal_y is not None:
        if focal:
            result["expected_focal"] = [args.expected_focal_x, args.expected_focal_y]
            result["match"] = (
                abs(focal[0] - args.expected_focal_x) < 1.0 and
                abs(focal[1] - args.expected_focal_y) < 1.0
            )
        else:
            result["match"] = False

    output_success(result, args.json)
    return 0


def cmd_batch_set(args):
    """Set multiple focal points from JSON file."""
    core = load_core_from_config()
    if core is None:
        output_error("No project initialized. Run 'init' first.", args.json)
        return 1

    import json
    try:
        with open(args.file, 'r') as f:
            focal_points = json.load(f)
    except Exception as e:
        output_error(f"Could not load file: {e}", args.json)
        return 1

    if not isinstance(focal_points, list):
        output_error("JSON file must contain an array", args.json)
        return 1

    count = 0
    for item in focal_points:
        if not isinstance(item, dict):
            continue
        idx = item.get("index")
        x = item.get("x")
        y = item.get("y")
        if idx is None or x is None or y is None:
            continue
        if 0 <= idx < core.total_images:
            core.navigate_to(idx)
            core.set_focal_point(x, y)
            count += 1

    core.save_focal_points()
    output_success({
        "message": f"Set {count} focal points",
        "count": count,
    }, args.json)
    return 0


def cmd_test_run(args):
    """Run a sequence of operations from JSON file."""
    import json
    try:
        with open(args.operations, 'r') as f:
            operations = json.load(f)
    except Exception as e:
        output_error(f"Could not load operations file: {e}", args.json)
        return 1

    if not isinstance(operations, list):
        output_error("JSON file must contain an array of operations", args.json)
        return 1

    results = []
    for i, op in enumerate(operations):
        if not isinstance(op, dict):
            results.append({"operation": i, "error": "Invalid operation format"})
            continue

        action = op.get("action")
        if action == "init":
            config = {
                "input_folder": op.get("input"),
                "target_width": op.get("width", 2560),
                "target_height": op.get("height", 1440),
            }
            if op.get("output"):
                config["output_folder"] = op.get("output")
            try:
                core = FocalPointAlignerCore(config)
                results.append({"operation": i, "action": "init", "success": True, "total_images": core.total_images})
            except Exception as e:
                results.append({"operation": i, "action": "init", "success": False, "error": str(e)})
                break

        elif action == "set-focal":
            idx = op.get("index", core.current_idx if core else 0)
            x = op.get("x")
            y = op.get("y")
            if core and x is not None and y is not None:
                core.navigate_to(idx)
                core.set_focal_point(x, y)
                results.append({"operation": i, "action": "set-focal", "index": idx, "focal": [x, y]})
            else:
                results.append({"operation": i, "action": "set-focal", "error": "Missing core or coordinates"})

        elif action == "save":
            if core:
                old_idx = core.current_idx
                core.confirm_and_save()
                results.append({"operation": i, "action": "save", "from": old_idx, "to": core.current_idx})
            else:
                results.append({"operation": i, "action": "save", "error": "No core initialized"})

        elif action == "export":
            if core:
                orientation = op.get("orientation", "landscape")
                core.set_alignment_mode(orientation)
                core.prepare_aligned_previews(orientation)
                results.append({"operation": i, "action": "export", "orientation": orientation})
            else:
                results.append({"operation": i, "action": "export", "error": "No core initialized"})

        else:
            results.append({"operation": i, "action": action, "error": "Unknown action"})

    output_success({
        "total_operations": len(operations),
        "results": results,
    }, args.json)
    return 0


def main():
    root_parser = argparse.ArgumentParser(add_help=False)
    root_parser.add_argument("--json", action="store_true")
    
    args, remaining = root_parser.parse_known_args()
    json_output = args.json
    
    parser = argparse.ArgumentParser(
        description="FocalPointAligner CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", parser_class=argparse.ArgumentParser)

    p = subparsers.add_parser("init", help="Initialize with input folder")
    p.add_argument("--input", required=True, help="Input folder path")
    p.add_argument("--output", help="Output folder path")
    p.add_argument("--width", type=int, default=2560, help="Target width")
    p.add_argument("--height", type=int, default=1440, help="Target height")
    p.add_argument("--gui", action="store_true", help="Launch GUI after initialization")

    p = subparsers.add_parser("status", help="Show current status")
    p.add_argument("--quiet", action="store_true", help="Quiet mode")

    p = subparsers.add_parser("navigate", help="Navigate images")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--index", type=int, help="Go to specific index")
    g.add_argument("--next", action="store_true", help="Go to next image")
    g.add_argument("--prev", action="store_true", help="Go to previous image")

    p = subparsers.add_parser("set-focal", help="Set focal point")
    p.add_argument("--x", type=int, required=True, help="X coordinate")
    p.add_argument("--y", type=int, required=True, help="Y coordinate")
    p.add_argument("--index", type=int, help="Image index (default: current)")

    p = subparsers.add_parser("save", help="Save current focal point and advance")

    p = subparsers.add_parser("skip", help="Skip to next image without saving")

    p = subparsers.add_parser("clear-focal", help="Clear focal point")
    p.add_argument("--index", type=int, help="Image index (default: current)")

    p = subparsers.add_parser("discard", help="Discard image")
    p.add_argument("--index", type=int, help="Image index (default: current)")

    p = subparsers.add_parser("reset", help="Reset all focal points")
    p.add_argument("--confirm", action="store_true", help="Skip confirmation prompt")

    p = subparsers.add_parser("export", help="Export aligned images")
    p.add_argument("--orientation", choices=["landscape", "portrait"], help="Orientation")

    p = subparsers.add_parser("stats", help="Show progress statistics")

    p = subparsers.add_parser("list-images", help="List images with status")
    p.add_argument("--with-focal", action="store_true", help="Only show with focal points")
    p.add_argument("--without-focal", action="store_true", help="Only show without focal points")

    p = subparsers.add_parser("get-image", help="Get image info or save to disk")
    p.add_argument("--index", type=int, required=True, help="Image index")
    p.add_argument("--type", choices=["original", "preview"], default="preview", help="Image type")
    p.add_argument("--orientation", choices=["landscape", "portrait"], help="Orientation")
    p.add_argument("--save-to", help="Save to specific path")

    p = subparsers.add_parser("verify-alignment", help="Verify focal point alignment")
    p.add_argument("--index", type=int, required=True, help="Image index")
    p.add_argument("--orientation", choices=["landscape", "portrait"], default="landscape", help="Orientation")
    p.add_argument("--expected-focal-x", type=float, help="Expected focal X")
    p.add_argument("--expected-focal-y", type=float, help="Expected focal Y")

    p = subparsers.add_parser("batch-set", help="Set multiple focal points from JSON file")
    p.add_argument("--file", required=True, help="JSON file with focal points")

    p = subparsers.add_parser("test-run", help="Run sequence of operations from JSON file")
    p.add_argument("--operations", required=True, help="JSON file with operations")
    
    args, unknown = parser.parse_known_args(remaining)
    
    args.json = json_output
    
    if args.command is None:
        parser.print_help()
        return 0

    commands = {
        "init": cmd_init,
        "status": cmd_status,
        "navigate": cmd_navigate,
        "set-focal": cmd_set_focal,
        "save": cmd_save,
        "skip": cmd_skip,
        "clear-focal": cmd_clear_focal,
        "discard": cmd_discard,
        "reset": cmd_reset,
        "export": cmd_export,
        "stats": cmd_stats,
        "list-images": cmd_list_images,
        "get-image": cmd_get_image,
        "verify-alignment": cmd_verify_alignment,
        "batch-set": cmd_batch_set,
        "test-run": cmd_test_run,
    }

    if args.command not in commands:
        parser.print_help()
        return 0

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())