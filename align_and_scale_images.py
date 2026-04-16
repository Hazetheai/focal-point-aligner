#!/usr/bin/env python3
"""
Sort images by focal point proximity and create aligned output.
Non-destructive: creates new folder, leaves originals untouched.
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def load_focal_points(json_path):
    with open(json_path, 'r') as f:
        return json.load(f)


def build_distance_matrix(focal_points_list):
    n = len(focal_points_list)
    dist_matrix = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            p1 = np.array(focal_points_list[i])
            p2 = np.array(focal_points_list[j])
            dist = np.linalg.norm(p1 - p2)
            dist_matrix[i][j] = dist
            dist_matrix[j][i] = dist
    return dist_matrix


def greedy_nearest_neighbor(dist_matrix, start_idx=0):
    n = len(dist_matrix)
    visited = [False] * n
    tour = [start_idx]
    visited[start_idx] = True
    
    for _ in range(n - 1):
        current = tour[-1]
        nearest = None
        nearest_dist = float('inf')
        for j in range(n):
            if not visited[j] and dist_matrix[current][j] < nearest_dist:
                nearest = j
                nearest_dist = dist_matrix[current][j]
        tour.append(nearest)
        visited[nearest] = True
    
    return tour


def calculate_tour_cost(tour, dist_matrix):
    cost = 0
    for i in range(len(tour) - 1):
        cost += dist_matrix[tour[i]][tour[i + 1]]
    return cost


def two_opt(tour, dist_matrix, max_iterations=1000):
    improved = True
    iterations = 0
    best_tour = tour.copy()
    best_cost = calculate_tour_cost(best_tour, dist_matrix)
    
    while improved and iterations < max_iterations:
        improved = False
        iterations += 1
        for i in range(1, len(best_tour) - 1):
            for j in range(i + 1, len(best_tour)):
                new_tour = best_tour[:i] + best_tour[i:j+1][::-1] + best_tour[j+1:]
                new_cost = calculate_tour_cost(new_tour, dist_matrix)
                if new_cost < best_cost:
                    best_tour = new_tour
                    best_cost = new_cost
                    improved = True
                    break
            if improved:
                break
    
    return best_tour


def sort_focal_points(focal_points_list):
    if len(focal_points_list) <= 2:
        return list(range(len(focal_points_list)))
    
    dist_matrix = build_distance_matrix(focal_points_list)
    
    best_tour = None
    best_cost = float('inf')
    
    for start in range(len(focal_points_list)):
        greedy_tour = greedy_nearest_neighbor(dist_matrix, start)
        optimized_tour = two_opt(greedy_tour, dist_matrix)
        cost = calculate_tour_cost(optimized_tour, dist_matrix)
        
        if cost < best_cost:
            best_cost = cost
            best_tour = optimized_tour
    
    return best_tour


def calculate_transformation(focal_x, focal_y, orig_w, orig_h, target_w, target_h):
    """
    Calculate transformation to center focal point and fill target frame.
    
    Strategy:
    1. Calculate minimum scale to fill target frame (based on aspect ratios)
    2. Calculate minimum scale so focal point can be centered (based on focal position)
    3. Use the larger of the two scales
    4. Translate so focal point is at target center
    5. Crop to target dimensions
    """
    half_target_w = target_w / 2
    half_target_h = target_h / 2
    
    scale_fill = max(orig_w / target_w, orig_h / target_h)
    
    scale_horizontal = max(
        half_target_w / focal_x if focal_x > 0 else float('inf'),
        half_target_w / (orig_w - focal_x) if (orig_w - focal_x) > 0 else float('inf')
    )
    
    scale_vertical = max(
        half_target_h / focal_y if focal_y > 0 else float('inf'),
        half_target_h / (orig_h - focal_y) if (orig_h - focal_y) > 0 else float('inf')
    )
    
    scale_focal = max(scale_horizontal, scale_vertical)
    
    scale = max(scale_fill, scale_focal)
    
    scaled_w = orig_w * scale
    scaled_h = orig_h * scale
    
    focal_scaled_x = focal_x * scale
    focal_scaled_y = focal_y * scale
    
    tx = half_target_w - focal_scaled_x
    ty = half_target_h - focal_scaled_y
    
    crop_x = -tx
    crop_y = -ty
    
    return crop_x, crop_y, scale, target_w, target_h


def main():
    parser = argparse.ArgumentParser(
        description="Sort images by focal point proximity and create aligned output"
    )
    parser.add_argument("input_folder", help="Path to folder containing original images and focal_points.json")
    parser.add_argument("--output", "-o", help="Output folder path (default: input_folder_aligned_v2)")
    parser.add_argument("--orientation", choices=["landscape", "portrait"], default="landscape",
                       help="Output orientation (default: landscape)")
    args = parser.parse_args()
    
    if args.orientation == "landscape":
        target_width = 2560
        target_height = 1440
    else:
        target_width = 1440
        target_height = 2560
    
    input_path = Path(args.input_folder)
    if not input_path.exists() or not input_path.is_dir():
        print(f"Error: {input_path} is not a valid directory")
        return 1
    
    json_path = input_path / "focal_points.json"
    if not json_path.exists():
        print(f"Error: {json_path} not found")
        return 1
    
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = input_path.parent / f"{input_path.name}_aligned_v2"
    
    output_path.mkdir(parents=True, exist_ok=True)
    
    print(f"Loading focal points from {json_path}")
    focal_data = load_focal_points(json_path)
    
    extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff'}
    image_files = sorted([
        f for f in input_path.iterdir()
        if f.is_file() and f.suffix.lower() in extensions
    ])
    
    with_focal = []
    without_focal = []
    
    for img_file in image_files:
        if img_file.name in focal_data:
            with_focal.append((img_file, focal_data[img_file.name]))
        else:
            without_focal.append(img_file)
    
    print(f"Found {len(with_focal)} images with focal points, {len(without_focal)} without")
    
    focal_points_list = [fp for _, fp in with_focal]
    
    if len(with_focal) > 0:
        print("Sorting images by focal point proximity...")
        sorted_focal_indices = sort_focal_points(focal_points_list)
        sorted_with_focal = [(with_focal[i][0], with_focal[i][1]) for i in sorted_focal_indices]
    else:
        sorted_with_focal = []
        sorted_focal_indices = []
    
    sorted_order = {}
    sorted_focal_points = {}
    
    for new_idx, (img_file, focal) in enumerate(sorted_with_focal):
        output_name = f"{new_idx + 1:04d}.jpg"
        sorted_order[img_file.name] = new_idx + 1
        sorted_focal_points[output_name] = focal
    
    missing_focal_points = {}
    
    for new_idx, img_file in enumerate(without_focal):
        img = cv2.imread(str(img_file))
        if img is None:
            continue
        h, w = img.shape[:2]
        center_focal = [w / 2, h / 2]
        output_idx = len(sorted_with_focal) + new_idx + 1
        output_name = f"{output_idx:04d}.jpg"
        sorted_order[img_file.name] = output_idx
        missing_focal_points[img_file.name] = center_focal
    
    total_images = len(sorted_with_focal) + len(without_focal)
    print(f"Optimal sequence found with {total_images} images total")
    
    with open(output_path / "focal_points.json", 'w') as f:
        json.dump(sorted_focal_points, f, indent=2)
    
    with open(output_path / "sorted_order.json", 'w') as f:
        json.dump(sorted_order, f, indent=2)
    
    with open(output_path / "missing_focal_points.json", 'w') as f:
        json.dump(missing_focal_points, f, indent=2)
    
    print(f"Processing {total_images} images...")
    
    all_images = sorted_with_focal + [(f, None) for f in without_focal]
    
    for idx, (img_file, focal) in enumerate(all_images):
        img = cv2.imread(str(img_file))
        
        if img is None:
            print(f"Warning: Could not read {img_file}")
            continue
        
        h, w = img.shape[:2]
        
        if focal is not None:
            focal_x, focal_y = focal
        else:
            focal_x, focal_y = w / 2, h / 2
        
        crop_x, crop_y, scale, crop_w, crop_h = calculate_transformation(
            focal_x, focal_y, w, h, target_width, target_height
        )
        
        scaled_w = int(w * scale)
        scaled_h = int(h * scale)
        scaled = cv2.resize(img, (scaled_w, scaled_h), interpolation=cv2.INTER_LANCZOS4)
        
        src_x = max(0, int(crop_x))
        src_y = max(0, int(crop_y))
        src_w = min(crop_w, scaled_w - src_x)
        src_h = min(crop_h, scaled_h - src_y)
        
        aligned = scaled[src_y:src_y + src_h, src_x:src_x + src_w]
        
        if aligned.shape[0] != crop_h or aligned.shape[1] != crop_w:
            aligned = cv2.resize(aligned, (crop_w, crop_h), interpolation=cv2.INTER_LANCZOS4)
        
        output_filename = f"{idx + 1:04d}.jpg"
        output_path_file = output_path / output_filename
        
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, 95]
        cv2.imwrite(str(output_path_file), aligned, encode_params)
        
        if (idx + 1) % 10 == 0 or idx == len(all_images) - 1:
            print(f"  Processed {idx + 1}/{len(all_images)} images")
    
    print(f"\nDone! Output saved to: {output_path}")
    print(f"  - {total_images} aligned images")
    print(f"  - focal_points.json")
    print(f"  - sorted_order.json")
    print(f"  - missing_focal_points.json ({len(without_focal)} images used center)")
    
    return 0


if __name__ == "__main__":
    exit(main())
