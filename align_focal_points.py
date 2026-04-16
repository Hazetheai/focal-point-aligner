#!/usr/bin/env python3
"""
Interactive tool for aligning images by selecting focal points.
Focal points are moved to center, then images are cropped to fill frame.
Features auto-save focal points to JSON for crash recovery.
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


WINDOW_NAME = "Focal Point Aligner"

DISPLAY_WIDTH = 1440
DISPLAY_HEIGHT = 1440

LOG_FILE = "align_focal_points.log"

def log(msg, file_only=False):
    """Log to both console and file."""
    print(msg)
    try:
        with open(LOG_FILE, "a") as f:
            from datetime import datetime
            timestamp = datetime.now().strftime("%H:%M:%S")
            f.write(f"[{timestamp}] {msg}\n")
    except:
        pass


def calculate_transformation(focal_x, focal_y, orig_w, orig_h, target_w, target_h):
    """
    Calculate transformation to center focal point and fill target frame.
    """
    focal_x = max(1, min(focal_x, orig_w - 1))
    focal_y = max(1, min(focal_y, orig_h - 1))
    
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
    
    if scale == float('inf') or scale > 100:
        scale = scale_fill
    
    scaled_w = orig_w * scale
    scaled_h = orig_h * scale
    
    focal_scaled_x = focal_x * scale
    focal_scaled_y = focal_y * scale
    
    tx = half_target_w - focal_scaled_x
    ty = half_target_h - focal_scaled_y
    
    crop_x = -tx
    crop_y = -ty
    
    return crop_x, crop_y, scale, target_w, target_h

HEADER_HEIGHT = 100
FOOTER_HEIGHT = 160
GAP = 20

THUMB_WIDTH = 350
THUMB_HEIGHT = 260
CURRENT_WIDTH = 700
MAIN_AREA_HEIGHT = 900
MAIN_AREA_Y = (DISPLAY_HEIGHT - MAIN_AREA_HEIGHT) // 2
THUMBNAIL_ROW_HEIGHT = 40


class FocalPointAligner:
    def __init__(self, input_folder, output_folder):
        self.input_folder = Path(input_folder)
        self.output_folder = Path(output_folder)
        self.output_folder.mkdir(parents=True, exist_ok=True)
        
        self.preview_folder = self.output_folder.parent / f"{self.output_folder.name}_preview"
        
        self.json_path = self.output_folder / "focal_points.json"
        
        self.show_aligned = False
        self.alignment_mode = None
        self.preview_state = {}
        self.pending_focal = None
        self.existing_focal = None
        
        if self.json_path.exists():
            try:
                with open(self.json_path, 'r') as f:
                    data = json.load(f)
                if "alignment_mode" in data and data["alignment_mode"]:
                    self.alignment_mode = data["alignment_mode"]
                if "preview_state" in data:
                    self.preview_state = data["preview_state"]
            except:
                pass
        
        if self.alignment_mode:
            self.preview_folder = self.output_folder.parent / f"{self.output_folder.name}_preview_{self.alignment_mode}"
        else:
            self.preview_folder = self.output_folder.parent / f"{self.output_folder.name}_preview"
        
        extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff'}
        self.image_files = sorted([
            f for f in self.input_folder.iterdir()
            if f.is_file() and f.suffix.lower() in extensions
        ])
        
        if not self.image_files:
            raise ValueError(f"No images found in {input_folder}")
        
        self.current_idx = 0
        self.focal_points = {}
        self.completed = set()
        
        self.load_focal_points()
        
        if self.image_files:
            sample_img = cv2.imread(str(self.image_files[0]))
            if sample_img is not None:
                self.ref_h, self.ref_w = sample_img.shape[:2]
            else:
                self.ref_h, self.ref_w = 1440, 2560
        else:
            self.ref_h, self.ref_w = 1440, 2560
        
        self.current_display_scale = 1.0
        self.current_display_w = CURRENT_WIDTH
        self.current_display_h = MAIN_AREA_HEIGHT
        self.current_display_offset_x = 0
        self.current_display_offset_y = 0
        
        self.current_focal = None
        self.base_display_image = None
        self.display_image = None
        self.prev_image_shape = (THUMB_HEIGHT, THUMB_WIDTH)
        self.next_image_shape = (THUMB_HEIGHT, THUMB_WIDTH)
        self.discarded = set()
        
        self.drag_start_idx = None
        self.drag_current_idx = None
        
        self.load_current_images()
    
    def load_focal_points(self):
        if self.json_path.exists():
            try:
                with open(self.json_path, 'r') as f:
                    data = json.load(f)
                
                if "alignment_mode" in data:
                    self.alignment_mode = data["alignment_mode"]
                    if self.alignment_mode:
                        print(f"Loaded alignment mode: {self.alignment_mode}")
                
                if "preview_state" in data:
                    self.preview_state = data["preview_state"]
                
                if "discarded" in data:
                    self.discarded = set(data["discarded"])
                
                focal_data = {k: v for k, v in data.items() if k not in ["alignment_mode", "preview_state", "discarded"]}
                
                existing_files = {f.name for f in self.image_files}
                
                for filename, coords in focal_data.items():
                    if filename not in existing_files:
                        continue
                    for idx, img_file in enumerate(self.image_files):
                        if img_file.name == filename:
                            self.focal_points[idx] = tuple(coords)
                            self.completed.add(idx)
                            break
                
                if self.focal_points:
                    completed_count = len(self.focal_points)
                    print(f"Loaded {completed_count} saved focal points from {self.json_path}")
                    
                    first_pending = 0
                    for i in range(len(self.image_files)):
                        if i not in self.completed:
                            first_pending = i
                            break
                    else:
                        first_pending = len(self.image_files) - 1
                    
                    self.current_idx = first_pending
                    print(f"Resuming at image {self.current_idx + 1}")
            except Exception as e:
                print(f"Warning: Could not load focal points: {e}")
    
    def save_focal_points(self):
        stale_indices = [idx for idx in self.focal_points.keys() if idx >= len(self.image_files)]
        for idx in stale_indices:
            del self.focal_points[idx]
            self.completed.discard(idx)
        
        data = {}
        for idx, focal in self.focal_points.items():
            if idx < len(self.image_files):
                filename = self.image_files[idx].name
                data[filename] = list(focal)
        
        if self.alignment_mode:
            data["alignment_mode"] = self.alignment_mode
        
        if self.preview_state:
            data["preview_state"] = self.preview_state
        
        if self.discarded:
            data["discarded"] = list(self.discarded)
        
        try:
            with open(self.json_path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Warning: Could not save focal points: {e}")
    
    def load_current_images(self):
        aligned_preview = None
        if self.show_aligned and self.alignment_mode:
            aligned_preview = self.get_aligned_preview_path(self.current_idx)
            log(f"[LOAD] get_aligned_preview_path({self.current_idx}) returned: {aligned_preview}")
        
        if aligned_preview:
            log(f"[LOAD] Loading from preview: {aligned_preview}")
            self.current_image = cv2.imread(str(aligned_preview))
            if self.current_image is None:
                log("[LOAD] Preview failed, falling back to original")
                self.current_image = cv2.imread(str(self.image_files[self.current_idx]))
                if self.current_image is None:
                    self.current_image = np.zeros((self.ref_h, self.ref_w, 3), dtype=np.uint8)
        else:
            log(f"[LOAD] Loading original image: {self.image_files[self.current_idx].name}")
            self.current_image = cv2.imread(str(self.image_files[self.current_idx]))
            if self.current_image is None:
                self.current_image = np.zeros((self.ref_h, self.ref_w, 3), dtype=np.uint8)
        
        orig_h, orig_w = self.current_image.shape[:2]
        
        display_scale = min(CURRENT_WIDTH / orig_w, MAIN_AREA_HEIGHT / orig_h)
        display_w = int(orig_w * display_scale)
        display_h = int(orig_h * display_scale)
        
        self.current_display_scale = display_scale
        self.current_display_w = display_w
        self.current_display_h = display_h
        self.current_display_offset_x = (CURRENT_WIDTH - display_w) // 2
        self.current_display_offset_y = (MAIN_AREA_HEIGHT - display_h) // 2
        
        self.base_display_image = cv2.resize(
            self.current_image, 
            (display_w, display_h), 
            interpolation=cv2.INTER_LANCZOS4
        )
        self.display_image = self.base_display_image.copy()
        
        self.current_focal = self.focal_points.get(self.current_idx)
        
        if not self.show_aligned:
            if self.existing_focal is not None:
                disp_x = int(self.existing_focal[0] * display_scale)
                disp_y = int(self.existing_focal[1] * display_scale)
                self.draw_focal_point(self.display_image, (disp_x, disp_y), color=(0, 255, 255), size=16)
            
            if self.pending_focal is not None:
                disp_x = int(self.pending_focal[0] * display_scale)
                disp_y = int(self.pending_focal[1] * display_scale)
                self.draw_focal_point(self.display_image, (disp_x, disp_y), color=(0, 0, 255), size=20)
            elif self.current_focal is not None:
                disp_x = int(self.current_focal[0] * display_scale)
                disp_y = int(self.current_focal[1] * display_scale)
                self.draw_focal_point(self.display_image, (disp_x, disp_y))
        
        self.current_has_saved_focal = self.current_idx in self.focal_points
        
        prev_idx = self.current_idx - 1
        next_idx = self.current_idx + 1
        
        self.prev_idx = prev_idx if prev_idx >= 0 else None
        self.next_idx = next_idx if next_idx < len(self.image_files) else None
        
        self.prev_image = None
        self.prev_image_shape = (THUMB_HEIGHT, THUMB_WIDTH)
        if prev_idx >= 0:
            prev_preview = self.get_aligned_preview_path(prev_idx) if self.show_aligned else None
            if prev_preview:
                img = cv2.imread(str(prev_preview))
            else:
                img = cv2.imread(str(self.image_files[prev_idx]))
            if img is not None:
                orig_h2, orig_w2 = img.shape[:2]
                if orig_w2 > orig_h2:
                    resized = cv2.resize(img, (THUMB_WIDTH, THUMB_HEIGHT), interpolation=cv2.INTER_LANCZOS4)
                    self.prev_image_shape = (THUMB_HEIGHT, THUMB_WIDTH)
                else:
                    thumb_h = int(THUMB_WIDTH * orig_h2 / orig_w2)
                    resized = cv2.resize(img, (THUMB_WIDTH, thumb_h), interpolation=cv2.INTER_LANCZOS4)
                    self.prev_image_shape = (thumb_h, THUMB_WIDTH)
                if not self.show_aligned and prev_idx in self.focal_points:
                    fp = self.focal_points[prev_idx]
                    disp_fp = (int(fp[0] * THUMB_WIDTH / orig_w2), int(fp[1] * THUMB_HEIGHT / orig_h2))
                    self.draw_focal_point(resized, disp_fp, color=(0, 255, 0), size=6)
                self.prev_image = resized
        
        self.next_image = None
        self.next_image_shape = (THUMB_HEIGHT, THUMB_WIDTH)
        if next_idx < len(self.image_files):
            next_preview = self.get_aligned_preview_path(next_idx) if self.show_aligned else None
            if next_preview:
                img = cv2.imread(str(next_preview))
            else:
                img = cv2.imread(str(self.image_files[next_idx]))
            if img is not None:
                orig_h2, orig_w2 = img.shape[:2]
                if orig_w2 > orig_h2:
                    resized = cv2.resize(img, (THUMB_WIDTH, THUMB_HEIGHT), interpolation=cv2.INTER_LANCZOS4)
                    self.next_image_shape = (THUMB_HEIGHT, THUMB_WIDTH)
                else:
                    thumb_h = int(THUMB_WIDTH * orig_h2 / orig_w2)
                    resized = cv2.resize(img, (THUMB_WIDTH, thumb_h), interpolation=cv2.INTER_LANCZOS4)
                    self.next_image_shape = (thumb_h, THUMB_WIDTH)
                if not self.show_aligned and next_idx in self.focal_points:
                    fp = self.focal_points[next_idx]
                    disp_fp = (int(fp[0] * THUMB_WIDTH / orig_w2), int(fp[1] * THUMB_HEIGHT / orig_h2))
                    self.draw_focal_point(resized, disp_fp, color=(0, 255, 0), size=6)
                self.next_image = resized
    
    def draw_focal_point(self, img, point, color=(0, 0, 255), size=20):
        x, y = int(point[0]), int(point[1])
        h, w = img.shape[:2]
        
        if 0 <= x < w and 0 <= y < h:
            cv2.circle(img, (x, y), size + 8, color, 2)
            cv2.drawMarker(img, (x, y), color, cv2.MARKER_TILTED_CROSS, size, 3)
            cv2.circle(img, (x, y), size // 2, color, 2)
            cv2.circle(img, (x, y), 3, (255, 255, 255), -1)
            
            center_x, center_y = w // 2, h // 2
            cv2.circle(img, (center_x, center_y), 10, (0, 255, 255), 2)
            cv2.circle(img, (center_x, center_y), 4, (0, 255, 255), -1)
            cv2.line(img, (x, y), (center_x, center_y), color, 2)
    
    def create_display(self):
        display = np.zeros((DISPLAY_HEIGHT, DISPLAY_WIDTH, 3), dtype=np.uint8)
        display[:, :] = (10, 10, 10)
        
        if self.show_aligned:
            if self.display_image is None:
                return display
            
            gap = 40
            available_width = DISPLAY_WIDTH - gap * 2
            available_height = DISPLAY_HEIGHT - HEADER_HEIGHT - 80
            
            if self.alignment_mode == "portrait":
                target_h = min(available_height, 1300)
                target_w = int(target_h * 9 / 16)
            else:
                target_h = min(available_height, 1100)
                target_w = int(target_h * 16 / 9)
            
            if target_w > available_width:
                target_w = available_width
                if self.alignment_mode == "portrait":
                    target_h = int(target_w * 16 / 9)
                else:
                    target_h = int(target_w * 9 / 16)
            
            center_x = (DISPLAY_WIDTH - target_w) // 2
            center_y = (DISPLAY_HEIGHT - target_h) // 2
            
            log(f"[DISPLAY] Preview mode | orig size: {self.current_image.shape[1]}x{self.current_image.shape[0]} | target: {target_w}x{target_h} | mode: {self.alignment_mode}")
            
            try:
                main_resized = cv2.resize(self.display_image, (target_w, target_h), interpolation=cv2.INTER_LANCZOS4)
                display[center_y:center_y+target_h, center_x:center_x+target_w] = main_resized
            except:
                pass
            
            info_text = f"Image {self.current_idx + 1} of {len(self.image_files)} | {self.alignment_mode.upper()}"
            text_size = cv2.getTextSize(info_text, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 1)[0]
            text_x = (DISPLAY_WIDTH - text_size[0]) // 2
            cv2.putText(display, info_text, 
                        (text_x, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 1)
            
            dots_y = DISPLAY_HEIGHT - 60
            num_dots = len(self.image_files)
            local_dots = 21
            page_size = 21
            
            if num_dots > 0:
                dot_radius = 8
                dot_gap = 30
                
                half_local = local_dots // 2
                start_idx = max(0, self.current_idx - half_local)
                end_idx = min(num_dots, self.current_idx + half_local + 1)
                
                if end_idx - start_idx < local_dots:
                    if start_idx == 0:
                        end_idx = min(num_dots, local_dots)
                    elif end_idx == num_dots:
                        start_idx = max(0, num_dots - local_dots)
                
                self._visible_dot_indices = list(range(start_idx, end_idx))
                
                total_pages = (num_dots + page_size - 1) // page_size
                current_page = self.current_idx // page_size
                
                total_local_width = len(self._visible_dot_indices) * dot_gap
                separator_gap = 40
                page_dot_gap = 35
                
                start_x = (DISPLAY_WIDTH - total_local_width - separator_gap - (total_pages * page_dot_gap)) // 2
                
                self._dots_info = (dots_y, start_x, dot_gap, start_idx, page_dot_gap, total_pages, current_page)
                
                for idx in self._visible_dot_indices:
                    display_idx = idx - start_idx
                    x_pos = start_x + display_idx * dot_gap + dot_gap // 2
                    
                    if idx == self.current_idx:
                        color = (0, 200, 255)
                        cv2.circle(display, (x_pos, dots_y), dot_radius + 3, color, 3)
                    elif idx in self.focal_points:
                        color = (0, 255, 100)
                    else:
                        color = (100, 100, 100)
                    cv2.circle(display, (x_pos, dots_y), dot_radius, color, -1)
                
                local_end_x = start_x + len(self._visible_dot_indices) * dot_gap
                
                if start_idx > 0:
                    cv2.putText(display, "...", (start_x - 30, dots_y + 5), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (80, 80, 80), 1)
                
                cv2.putText(display, "...", (local_end_x + 5, dots_y + 5), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (80, 80, 80), 1)
                
                page_start_x = local_end_x + separator_gap
                
                for page_num in range(total_pages):
                    x_pos = page_start_x + page_num * page_dot_gap + page_dot_gap // 2
                    
                    if page_num == current_page:
                        color = (0, 200, 255)
                        cv2.circle(display, (x_pos, dots_y), dot_radius + 3, color, 3)
                    else:
                        color = (150, 150, 150)
                    cv2.circle(display, (x_pos, dots_y), dot_radius, color, -1)
                
                self._page_dot_info = (page_start_x, page_dot_gap, page_size, total_pages)
        
        if self.show_aligned:
            return display
        
        cv2.rectangle(display, (0, 0), (DISPLAY_WIDTH, HEADER_HEIGHT), (45, 45, 45), -1)
        
        if self.current_focal is not None:
            status_color = (0, 255, 100)
            status_text = "FOCAL SET"
        elif self.current_idx in self.completed:
            status_color = (100, 255, 100)
            status_text = "SAVED"
        else:
            status_color = (180, 180, 180)
            status_text = "PENDING"
        
        cv2.putText(display, f"IMAGE {self.current_idx + 1} / {len(self.image_files)}", 
                    (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
        cv2.putText(display, status_text, 
                    (20, 62), cv2.FONT_HERSHEY_SIMPLEX, 0.7, status_color, 2)
        
        filename = self.image_files[self.current_idx].name
        
        if not self.show_aligned and self.current_focal is not None:
            fp_text = f"FOCAL: ({int(self.current_focal[0])}, {int(self.current_focal[1])})"
            cv2.putText(display, fp_text,
                        (500, 62), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 200), 1)
        elif not self.show_aligned and self.pending_focal is not None:
            fp_text = f"FOCAL: ({int(self.pending_focal[0])}, {int(self.pending_focal[1])})"
            cv2.putText(display, fp_text,
                        (500, 62), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 150, 255), 1)
        
        completed_text = f"Completed: {len(self.completed)} / {len(self.image_files)}"
        text_size = cv2.getTextSize(completed_text, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 1)[0]
        cv2.putText(display, completed_text, 
                    (DISPLAY_WIDTH - 20 - text_size[0], 62), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        
        if self.show_aligned and self.alignment_mode:
            mode_text = f"MODE: ALIGNED [{self.alignment_mode[:3].upper()}]"
            mode_color = (0, 255, 100)
        else:
            mode_text = "MODE: ORIGINAL"
            mode_color = (150, 150, 150)
        cv2.putText(display, mode_text, 
                    (DISPLAY_WIDTH // 2 - 60, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.7, mode_color, 2)
        
        thumb_y = MAIN_AREA_Y + (MAIN_AREA_HEIGHT - THUMB_HEIGHT) // 2
        thumb_overlap = 50
        
        prev_x = 0
        next_x = DISPLAY_WIDTH - (THUMB_WIDTH - thumb_overlap)
        
        center_v = MAIN_AREA_Y + MAIN_AREA_HEIGHT // 2
        
        if self.prev_image is not None:
            ph, pw = self.prev_image_shape
            py_center = center_v - ph // 2
            
            half_w = pw // 2
            src_x = half_w
            display[py_center:py_center + ph, prev_x:prev_x + half_w] = self.prev_image[:, src_x:src_x + half_w]
            cv2.putText(display, "PREV", 
                        (10, thumb_y + 20), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (150, 255, 150), 2)
        else:
            ph = THUMB_HEIGHT
            py_center = center_v - ph // 2
            cv2.rectangle(display, (prev_x, py_center), (prev_x + THUMB_WIDTH // 2, py_center + ph), (35, 35, 35), -1)
            cv2.putText(display, "FIRST", 
                        (10, center_v + 5), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (70, 70, 70), 2)
        
        if self.next_image is not None:
            nh, nw = self.next_image_shape
            ny_center = center_v - nh // 2
            
            half_w = nw // 2
            display[ny_center:ny_center + nh, next_x:next_x + half_w] = self.next_image[:, :half_w]
            cv2.putText(display, "NEXT", 
                        (next_x + 10, thumb_y + 20), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (150, 255, 150), 2)
        else:
            nh = THUMB_HEIGHT
            ny_center = center_v - nh // 2
            cv2.rectangle(display, (next_x, ny_center), 
                         (next_x + THUMB_WIDTH // 2, ny_center + nh), (35, 35, 35), -1)
            cv2.putText(display, "LAST", 
                        (next_x + 10, center_v + 5), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (70, 70, 70), 2)
        
        current_x = (DISPLAY_WIDTH - CURRENT_WIDTH) // 2
        
        display_region = np.zeros((MAIN_AREA_HEIGHT, CURRENT_WIDTH, 3), dtype=np.uint8)
        display_region[:, :] = (30, 30, 30)
        
        offset_x = self.current_display_offset_x
        offset_y = self.current_display_offset_y
        
        display_region[offset_y:offset_y+self.current_display_h, 
                       offset_x:offset_x+self.current_display_w] = self.display_image
        
        display[MAIN_AREA_Y:MAIN_AREA_Y+MAIN_AREA_HEIGHT, 
                current_x:current_x+CURRENT_WIDTH] = display_region
        cv2.rectangle(display, (current_x, MAIN_AREA_Y), 
                      (current_x+CURRENT_WIDTH, MAIN_AREA_Y+MAIN_AREA_HEIGHT), (80, 80, 80), 2)
        
        filename = self.image_files[self.current_idx].name
        text_size = cv2.getTextSize(filename, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0]
        text_x = current_x + (CURRENT_WIDTH - text_size[0]) // 2
        cv2.putText(display, filename, 
                    (text_x, MAIN_AREA_Y + MAIN_AREA_HEIGHT + 20), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (140, 140, 140), 1)
        
        footer_y = DISPLAY_HEIGHT - FOOTER_HEIGHT
        
        cv2.rectangle(display, (0, footer_y), (DISPLAY_WIDTH, DISPLAY_HEIGHT), (40, 40, 40), -1)
        
        bar_width = DISPLAY_WIDTH - 250
        bar_x = 20
        bar_y = footer_y + 15
        bar_height = 25
        
        cv2.rectangle(display, (bar_x, bar_y), (bar_x + bar_width, bar_y + bar_height), (20, 20, 20), -1)
        
        progress = len(self.completed) / len(self.image_files) if self.image_files else 0
        cv2.rectangle(display, (bar_x, bar_y), 
                      (bar_x + int(bar_width * progress), bar_y + bar_height), (0, 180, 0), -1)
        
        percent_text = f"{int(progress * 100)}%"
        cv2.putText(display, percent_text, 
                    (bar_x + bar_width + 10, bar_y + 18), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        
        controls_y = footer_y + 55
        controls = [
            "LEFT/RIGHT: Navigate  |  ENTER: Save & Next  |  SPACE: Skip  |  P: Preview  |  O: Orientation  |  DEL: Delete  |  X: Discard  |  R: Reset  |  ESC: Quit"
        ]
        cv2.putText(display, controls[0], 
                    (20, controls_y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (150, 150, 150), 1)
        
        help_y = footer_y + 80
        help_text = "Click on image to set focal point"
        cv2.putText(display, help_text, 
                    (20, help_y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (120, 120, 120), 1)
        
        pos_text = f"Position: {self.current_idx + 1} / {len(self.image_files)}"
        text_size = cv2.getTextSize(pos_text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)[0]
        pos_x = DISPLAY_WIDTH - text_size[0] - 30
        cv2.putText(display, pos_text, (pos_x, controls_y + 5), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (150, 150, 150), 1)
        
        dots_y = DISPLAY_HEIGHT - 60
        num_dots = len(self.image_files)
        local_dots = 21
        page_size = 21
        
        if num_dots > 0:
            dot_radius = 8
            dot_gap = 30
            
            half_local = local_dots // 2
            start_idx = max(0, self.current_idx - half_local)
            end_idx = min(num_dots, self.current_idx + half_local + 1)
            
            if end_idx - start_idx < local_dots:
                if start_idx == 0:
                    end_idx = min(num_dots, local_dots)
                elif end_idx == num_dots:
                    start_idx = max(0, num_dots - local_dots)
            
            self._visible_dot_indices = list(range(start_idx, end_idx))
            
            total_pages = (num_dots + page_size - 1) // page_size
            current_page = self.current_idx // page_size
            
            total_local_width = len(self._visible_dot_indices) * dot_gap
            separator_gap = 40
            page_dot_gap = 35
            
            start_x = (DISPLAY_WIDTH - total_local_width - separator_gap - (total_pages * page_dot_gap)) // 2
            
            self._dots_info = (dots_y, start_x, dot_gap, start_idx, page_dot_gap, total_pages, current_page)
            
            for idx in self._visible_dot_indices:
                display_idx = idx - start_idx
                x_pos = start_x + display_idx * dot_gap + dot_gap // 2
                
                if idx == self.current_idx:
                    color = (0, 200, 255)
                    cv2.circle(display, (x_pos, dots_y), dot_radius + 3, color, 3)
                elif idx in self.focal_points:
                    color = (0, 255, 100)
                else:
                    color = (100, 100, 100)
                cv2.circle(display, (x_pos, dots_y), dot_radius, color, -1)
            
            local_end_x = start_x + len(self._visible_dot_indices) * dot_gap
            
            if start_idx > 0:
                cv2.putText(display, "...", (start_x - 30, dots_y + 5), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (80, 80, 80), 1)
            
            cv2.putText(display, "...", (local_end_x + 5, dots_y + 5), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (80, 80, 80), 1)
            
            page_start_x = local_end_x + separator_gap
            
            for page_num in range(total_pages):
                x_pos = page_start_x + page_num * page_dot_gap + page_dot_gap // 2
                
                if page_num == current_page:
                    color = (0, 200, 255)
                    cv2.circle(display, (x_pos, dots_y), dot_radius + 3, color, 3)
                else:
                    color = (150, 150, 150)
                cv2.circle(display, (x_pos, dots_y), dot_radius, color, -1)
            
            self._page_dot_info = (page_start_x, page_dot_gap, page_size, total_pages)
        
        return display
    
    def refresh_display(self):
        display = self.create_display()
        cv2.imshow(WINDOW_NAME, display)
    
    def on_mouse(self, event, x, y, flags, param):
        thumb_y = MAIN_AREA_Y + (MAIN_AREA_HEIGHT - THUMB_HEIGHT) // 2
        prev_x = 0
        next_x = DISPLAY_WIDTH - (THUMB_WIDTH // 2)
        current_x = (DISPLAY_WIDTH - CURRENT_WIDTH) // 2
        
        if event == cv2.EVENT_LBUTTONDOWN:
            dots_y = DISPLAY_HEIGHT - 60
            num_dots = len(self.image_files)
            dots_info = getattr(self, '_dots_info', None)
            page_dot_info = getattr(self, '_page_dot_info', None)
            
            if num_dots > 0 and dots_info is not None and y >= dots_y - 40:
                _, start_x, dot_gap, start_idx, page_dot_gap, total_pages, current_page = dots_info
                
                for i in self._visible_dot_indices:
                    display_idx = i - start_idx
                    x_pos = start_x + display_idx * dot_gap + dot_gap // 2
                    if abs(x - x_pos) <= 20:
                        if i != self.current_idx:
                            self.current_idx = i
                            self.pending_focal = None
                            self.existing_focal = None
                            self.load_current_images()
                            print(f"Navigated to image {self.current_idx + 1}")
                            self.refresh_display()
                        return
                
                if page_dot_info is not None:
                    page_start_x, p_dot_gap, page_size, p_total_pages = page_dot_info
                    for page_num in range(p_total_pages):
                        x_pos = page_start_x + page_num * p_dot_gap + p_dot_gap // 2
                        if abs(x - x_pos) <= 20:
                            new_idx = page_num * page_size
                            if new_idx != self.current_idx:
                                self.current_idx = new_idx
                                self.pending_focal = None
                                self.existing_focal = None
                                self.load_current_images()
                                print(f"Jumped to page {page_num + 1}, image {self.current_idx + 1}")
                                self.refresh_display()
                            return
            
            if current_x <= x < current_x + CURRENT_WIDTH:
                if self.show_aligned:
                    return
                
                image_top = MAIN_AREA_Y + self.current_display_offset_y
                image_bottom = image_top + self.current_display_h
                
                if not (image_top <= y <= image_bottom):
                    return
                
                local_x = x - current_x
                img_x = local_x - self.current_display_offset_x
                img_y = y - image_top
                
                orig_x = img_x / self.current_display_scale
                orig_y = img_y / self.current_display_scale
                
                self.existing_focal = self.focal_points.get(self.current_idx)
                self.pending_focal = (float(orig_x), float(orig_y))
                
                self.current_focal = self.pending_focal
                self.current_has_saved_focal = False
                
                self.display_image = self.base_display_image.copy()
                
                if self.existing_focal is not None:
                    disp_x = int(self.existing_focal[0] * self.current_display_scale)
                    disp_y = int(self.existing_focal[1] * self.current_display_scale)
                    self.draw_focal_point(self.display_image, (disp_x, disp_y), color=(0, 255, 255), size=16)
                
                disp_x = int(orig_x * self.current_display_scale)
                disp_y = int(orig_y * self.current_display_scale)
                self.draw_focal_point(self.display_image, (disp_x, disp_y), color=(0, 0, 255), size=20)
                
                print(f"Focal point set at original coords: ({orig_x:.1f}, {orig_y:.1f})")
                self.refresh_display()
                return
    
    def confirm_and_save(self):
        if self.current_focal is None and self.pending_focal is None:
            print("No focal point selected - press ENTER again to skip, or click on image to set focal point")
            return False
        
        was_already_completed = self.current_idx in self.completed
        old_focal = self.focal_points.get(self.current_idx)
        
        if self.pending_focal is not None:
            save_focal = self.pending_focal
        else:
            save_focal = self.current_focal
        
        self.focal_points[self.current_idx] = save_focal
        self.completed.add(self.current_idx)
        self.current_has_saved_focal = True
        
        self.pending_focal = None
        self.existing_focal = None
        
        self.save_aligned_image()
        
        self.align_single_image(self.current_idx, self.image_files[self.current_idx], save_focal)
        
        if self.alignment_mode is not None:
            other_orientation = "portrait" if self.alignment_mode == "landscape" else "landscape"
            other_folder = self.output_folder.parent / f"{self.output_folder.name}_preview_{other_orientation}"
            old_folder = self.preview_folder
            self.preview_folder = other_folder
            self.preview_folder.mkdir(parents=True, exist_ok=True)
            self.align_single_image(self.current_idx, self.image_files[self.current_idx], save_focal)
            self.preview_folder = old_folder
        
        self.save_focal_points()
        
        if was_already_completed and old_focal != tuple(save_focal):
            self.show_updated_message()
            self.load_current_images()
            self.refresh_display()
            return "stay"
        elif self.current_idx < len(self.image_files) - 1:
            self.current_idx += 1
            self.load_current_images()
            return True
        else:
            return "stay"
    
    def show_updated_message(self):
        cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_AUTOSIZE)
        start_time = cv2.getTickCount()
        duration_ms = 1500
        total_ticks = duration_ms * cv2.getTickFrequency() / 1000
        
        while (cv2.getTickCount() - start_time) < total_ticks:
            display = self.create_display()
            
            elapsed = (cv2.getTickCount() - start_time) / cv2.getTickFrequency() * 1000
            remaining_pct = 1.0 - (elapsed / duration_ms)
            
            overlay_x = DISPLAY_WIDTH - 180
            overlay_y = HEADER_HEIGHT + 20
            cv2.rectangle(display, (overlay_x, overlay_y), (overlay_x + 160, overlay_y + 30), (0, 0, 0), -1)
            cv2.rectangle(display, (overlay_x, overlay_y), (overlay_x + 160, overlay_y + 30), (0, 255, 100), 1)
            
            cv2.putText(display, "Focal point updated",
                        (overlay_x + 10, overlay_y + 18),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 100), 1)
            
            bar_width = 140
            bar_x = overlay_x + 10
            bar_y = overlay_y + 22
            cv2.rectangle(display, (bar_x, bar_y), (bar_x + bar_width, bar_y + 6), (40, 40, 40), -1)
            cv2.rectangle(display, (bar_x, bar_y), (bar_x + int(bar_width * remaining_pct), bar_y + 6), (0, 255, 100), -1)
            
            cv2.imshow(WINDOW_NAME, display)
            cv2.waitKey(30)
    
    def skip_to_next(self):
        if self.current_idx < len(self.image_files) - 1:
            self.current_idx += 1
            self.pending_focal = None
            self.existing_focal = None
            self.load_current_images()
            return True
        else:
            return "stay"
    
    def save_aligned_image(self):
        img = self.current_image.copy()
        h, w = img.shape[:2]
        fx, fy = self.focal_points[self.current_idx]
        
        center = np.array([w / 2, h / 2])
        focal = np.array([fx, fy])
        translation = center - focal
        
        M = np.float32([[1, 0, translation[0]], [0, 1, translation[1]]])
        aligned = cv2.warpAffine(img, M, (w, h), borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))
        
        output_name = f"{self.current_idx + 1:04d}.jpg"
        output_path = self.output_folder / output_name
        cv2.imwrite(str(output_path), aligned, [cv2.IMWRITE_JPEG_QUALITY, 95])
    
    def delete_current(self):
        if self.current_idx in self.completed:
            del self.focal_points[self.current_idx]
            self.completed.remove(self.current_idx)
            self.save_focal_points()
            print(f"Deleted focal point for image {self.current_idx + 1}")
        
        self.current_focal = None
        self.current_has_saved_focal = False
        self.display_image = self.base_display_image.copy()
        
        if self.current_idx > 0:
            self.current_idx -= 1
            self.load_current_images()
            return True
        else:
            self.load_current_images()
            return True
    
    def discard_current(self):
        current_file = self.image_files[self.current_idx]
        discard_folder = self.input_folder / "discarded"
        discard_folder.mkdir(exist_ok=True)
        
        dest = discard_folder / current_file.name
        import shutil
        shutil.move(str(current_file), str(dest))
        
        self.discarded.add(current_file.name)
        if self.current_idx in self.focal_points:
            del self.focal_points[self.current_idx]
            self.completed.discard(self.current_idx)
        
        self.save_focal_points()
        
        extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff'}
        self.image_files = sorted([
            f for f in self.input_folder.iterdir()
            if f.is_file() and f.suffix.lower() in extensions
        ])
        
        if len(self.image_files) > self.current_idx:
            pass
        elif self.current_idx > 0:
            self.current_idx -= 1
        else:
            self.current_idx = 0
        
        if self.image_files:
            self.load_current_images()
        else:
            self.current_idx = 0
            self.current_image = np.zeros((self.ref_h, self.ref_w, 3), dtype=np.uint8)
            self.display_image = self.current_image
            self.base_display_image = self.current_image
        
        print(f"Discarded {current_file.name} | Remaining: {len(self.image_files)}")
        self.refresh_display()
    
    def reorder_images(self, from_idx, to_idx):
        log(f"[REORDER] Swapping index {from_idx} ({self.image_files[from_idx].name}) with {to_idx} ({self.image_files[to_idx].name})")
        
        self.image_files[from_idx], self.image_files[to_idx] = self.image_files[to_idx], self.image_files[from_idx]
        
        new_focal_points = {}
        for old_idx, focal in self.focal_points.items():
            if old_idx == from_idx:
                new_focal_points[to_idx] = focal
            elif old_idx == to_idx:
                new_focal_points[from_idx] = focal
            else:
                new_focal_points[old_idx] = focal
        self.focal_points = new_focal_points
        
        new_completed = set()
        for idx in self.completed:
            if idx == from_idx:
                new_completed.add(to_idx)
            elif idx == to_idx:
                new_completed.add(from_idx)
            else:
                new_completed.add(idx)
        self.completed = new_completed
        
        if self.current_idx == from_idx:
            self.current_idx = to_idx
        elif self.current_idx == to_idx:
            self.current_idx = from_idx
        
        self.save_focal_points()
        self.load_current_images()
        log(f"[REORDER] Complete. Current index: {self.current_idx}, image: {self.image_files[self.current_idx].name}")
    
    def reset_current(self):
        self.current_focal = None
        self.current_has_saved_focal = False
        self.display_image = self.base_display_image.copy()
    
    def navigate(self, direction):
        new_idx = self.current_idx + direction
        if 0 <= new_idx < len(self.image_files):
            log(f"[NAV] navigate({direction}) | {self.current_idx} -> {new_idx} | {self.image_files[new_idx].name}")
            self.current_idx = new_idx
            self.pending_focal = None
            self.existing_focal = None
            self.load_current_images()
            return True
        return False
    
    def navigate_wrap(self, direction):
        old_idx = self.current_idx
        if direction == -1:
            self.current_idx = (self.current_idx - 1) % len(self.image_files)
        else:
            self.current_idx = (self.current_idx + 1) % len(self.image_files)
        log(f"[NAV] navigate_wrap({direction}) | {old_idx} -> {self.current_idx} | {self.image_files[self.current_idx].name}")
        self.pending_focal = None
        self.existing_focal = None
        self.load_current_images()
        return True
    
    def shift_current(self, direction):
        if direction == -1:
            if self.current_idx > 0:
                self.reorder_images(self.current_idx, self.current_idx - 1)
                print(f"Shifted left. Now at position {self.current_idx + 1}")
                self.refresh_display()
            else:
                print("Already at first position")
        else:
            if self.current_idx < len(self.image_files) - 1:
                self.reorder_images(self.current_idx, self.current_idx + 1)
                print(f"Shifted right. Now at position {self.current_idx + 1}")
                self.refresh_display()
            else:
                print("Already at last position")
    
    def jump_to_position(self, position):
        try:
            pos = int(position)
            if 1 <= pos <= len(self.image_files):
                self.current_idx = pos - 1
                self.pending_focal = None
                self.existing_focal = None
                self.load_current_images()
                print(f"Jumped to image {self.current_idx + 1}")
                self.refresh_display()
            else:
                print(f"Position must be between 1 and {len(self.image_files)}")
        except ValueError:
            print("Invalid position input")
    
    def show_completion_menu(self):
        cv2.waitKey(100)
        cv2.destroyAllWindows()
        cv2.waitKey(100)
        
        print("\n" + "=" * 50)
        print("COMPLETED")
        print(f"Completed: {len(self.completed)} / {len(self.image_files)} images")
        print("=" * 50)
        print("\nChoose an option:")
        print("  [1] Back to Focal Point Aligner")
        print("  [2] Exit")
        print("  [3] Generate Landscape (final)")
        print("  [4] Generate Portrait (final)")
        print("\nEnter choice (1-4): ", end="", flush=True)
        
        while True:
            try:
                choice = input().strip()
                if choice == "1":
                    return "back"
                elif choice == "2":
                    return "quit"
                elif choice == "3":
                    return "transform_landscape"
                elif choice == "4":
                    return "transform_portrait"
                else:
                    print("Invalid choice. Enter 1-4: ", end="", flush=True)
            except EOFError:
                return "quit"
            except KeyboardInterrupt:
                return "quit"
    
    def run(self):
        while True:
            cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_AUTOSIZE)
            cv2.setMouseCallback(WINDOW_NAME, self.on_mouse)
            self.refresh_display()
            
            result = self.run_main_loop()
            cv2.destroyAllWindows()
            
            if result == "back":
                continue
            elif result in ["transform_landscape", "transform_portrait"]:
                return result
            elif result == "quit":
                return result
    
    def run_main_loop(self):
        last_nav_time = 0
        nav_delay_ms = 150
        
        while True:
            if self.show_aligned:
                key = cv2.waitKey(10) & 0xFF
                current_time = cv2.getTickCount()
                
                if key == 27:
                    return "quit"
                elif key == 80 or key == 112:
                    self.toggle_preview_mode()
                elif key == 84 or key == 116:
                    self.toggle_preview_mode()
                elif key == 79 or key == 111:
                    old_mode = self.alignment_mode
                    old_idx = self.current_idx
                    if not self.alignment_mode:
                        self.alignment_mode = "landscape"
                    if self.alignment_mode == "landscape":
                        self.alignment_mode = "portrait"
                    else:
                        self.alignment_mode = "landscape"
                    self.preview_folder = self.output_folder.parent / f"{self.output_folder.name}_preview_{self.alignment_mode}"
                    self.preview_folder.mkdir(parents=True, exist_ok=True)
                    log(f"[ORIENT] Changed orientation | {old_mode} -> {self.alignment_mode} | current_idx was {old_idx}, now {self.current_idx}")
                    self.save_focal_points()
                    self.prepare_aligned_previews()
                    self.load_current_images()
                    self.refresh_display()
                    log(f"[ORIENT] After reload | current_idx={self.current_idx}, image={self.image_files[self.current_idx].name if self.current_idx < len(self.image_files) else 'N/A'}")
                elif key in (81, 113, 123, 2424832):
                    self.navigate_wrap(-1)
                    print(f"Navigated to image {self.current_idx + 1}")
                    self.refresh_display()
                elif key in (83, 115, 124, 2555904):
                    self.navigate_wrap(1)
                    print(f"Navigated to image {self.current_idx + 1}")
                    self.refresh_display()
                continue
            
            key = cv2.waitKey(0) & 0xFF
            
            if key == 27:
                return "quit"
            elif key == 13:
                result = self.confirm_and_save()
                if result == "stay":
                    pass
                elif result:
                    print(f"Saved. Moved to image {self.current_idx + 1} | {len(self.completed)}/{len(self.image_files)} done")
                    self.refresh_display()
                else:
                    pass
            elif key == 32:
                result = self.skip_to_next()
                if result == "stay":
                    pass
                elif result:
                    print(f"Skipped. Moved to image {self.current_idx + 1}")
                    self.refresh_display()
            elif key == 70 or key == 102:
                return self.show_completion_menu()
            elif key == 10:
                return self.show_completion_menu()
            elif key == 8:
                if self.delete_current():
                    print(f"Deleted. Went to image {self.current_idx + 1}")
                    self.refresh_display()
            elif key == 88 or key == 120:
                self.discard_current()
            elif key == 82 or key == 114:
                self.reset_current()
                print(f"Reset focal point for image {self.current_idx + 1}")
                self.refresh_display()
            elif key in (81, 113, 123, 2424832):
                self.navigate_wrap(-1)
                print(f"Navigated to image {self.current_idx + 1}")
                self.refresh_display()
            elif key in (83, 115, 124, 2555904):
                self.navigate_wrap(1)
                print(f"Navigated to image {self.current_idx + 1}")
                self.refresh_display()
            elif key == 50:
                new_idx = max(0, self.current_idx - 20)
                self.current_idx = new_idx
                self.pending_focal = None
                self.existing_focal = None
                self.load_current_images()
                print(f"Page jump back to image {self.current_idx + 1}")
                self.refresh_display()
            elif key == 51:
                new_idx = min(len(self.image_files) - 1, self.current_idx + 20)
                self.current_idx = new_idx
                self.pending_focal = None
                self.existing_focal = None
                self.load_current_images()
                print(f"Page jump forward to image {self.current_idx + 1}")
                self.refresh_display()
            elif key == 91:
                self.shift_current(-1)
            elif key == 93:
                self.shift_current(1)
            elif key == 103:
                print(f"Current position: {self.current_idx + 1} / {len(self.image_files)}")
            elif key == 80 or key == 112:
                self.toggle_preview_mode()
            elif key == 84 or key == 116:
                self.toggle_preview_mode()
            elif key == 79 or key == 111:
                if self.show_aligned:
                    if not self.alignment_mode:
                        self.alignment_mode = "landscape"
                    if self.alignment_mode == "landscape":
                        self.alignment_mode = "portrait"
                    else:
                        self.alignment_mode = "landscape"
                    self.preview_folder = self.output_folder.parent / f"{self.output_folder.name}_preview_{self.alignment_mode}"
                    self.preview_folder.mkdir(parents=True, exist_ok=True)
                    print(f"Switched to {self.alignment_mode} mode")
                    self.save_focal_points()
                    
                    self.prepare_aligned_previews()
                    
                    self.load_current_images()
                    self.refresh_display()
                else:
                    print("Switch to Preview mode first (press P)")
    
    def toggle_preview_mode(self):
        log(f"[MODE] toggle_preview_mode called | current: show_aligned={self.show_aligned}, alignment_mode={self.alignment_mode}, current_idx={self.current_idx}")
        
        if self.show_aligned:
            self.show_aligned = False
            log(f"[MODE] Switched to ORIGINAL mode | current_idx={self.current_idx}")
            self.load_current_images()
            self.refresh_display()
            return
        
        if self.alignment_mode is None:
            result = self.show_mode_selection_menu()
            if result == "quit" or result is None:
                return
            self.alignment_mode = result
            self.preview_folder = self.output_folder.parent / f"{self.output_folder.name}_preview_{self.alignment_mode}"
            self.preview_folder.mkdir(parents=True, exist_ok=True)
            log(f"[MODE] Selected {self.alignment_mode} mode")
            self.save_focal_points()
        
        log(f"[MODE] Entering PREVIEW mode | alignment_mode={self.alignment_mode}, current_idx={self.current_idx}")
        self.prepare_aligned_previews()
        
        self.show_aligned = True
        self.load_current_images()
        self.refresh_display()
        
        log(f"[MODE] Now in PREVIEW mode | show_aligned={self.show_aligned}, current_idx={self.current_idx}")
    
    def show_mode_selection_menu(self):
        cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_AUTOSIZE)
        
        while True:
            display = np.zeros((DISPLAY_HEIGHT, DISPLAY_WIDTH, 3), dtype=np.uint8)
            display[:, :] = (25, 25, 25)
            
            cv2.rectangle(display, (200, 150), (1000, 450), (50, 50, 50), -1)
            cv2.rectangle(display, (200, 150), (1000, 450), (100, 100, 100), 3)
            
            cv2.putText(display, "SELECT ALIGNMENT MODE", 
                        (350, 200), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
            
            cv2.putText(display, "1) Landscape (16:9)", 
                        (300, 270), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)
            cv2.putText(display, "2) Portrait (9:16)", 
                        (300, 310), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)
            cv2.putText(display, "3) Back", 
                        (300, 350), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (150, 150, 150), 2)
            
            cv2.imshow(WINDOW_NAME, display)
            key = cv2.waitKey(0) & 0xFF
            
            if key == 49:
                return "landscape"
            elif key == 50:
                return "portrait"
            elif key == 51 or key == 27:
                return None
    
    def prepare_aligned_previews(self):
        log(f"[PREVIEW] prepare_aligned_previews called | folder: {self.preview_folder}")
        
        existing_preview_count = len(list(self.preview_folder.glob("*.jpg")))
        
        if existing_preview_count != len(self.image_files):
            log(f"[PREVIEW] Preview count mismatch: {existing_preview_count} previews vs {len(self.image_files)} images. Clearing and re-aligning...")
            for f in self.preview_folder.glob("*.jpg"):
                f.unlink()
        
        files_to_align = []
        for idx, img_file in enumerate(self.image_files):
            current_focal = self.focal_points.get(idx)
            if current_focal is None:
                img = cv2.imread(str(img_file))
                if img is not None:
                    h, w = img.shape[:2]
                    current_focal = (w / 2, h / 2)
                    self.focal_points[idx] = current_focal
            
            preview_path = self.preview_folder / f"{idx + 1:04d}.jpg"
            
            if not preview_path.exists() and current_focal is not None:
                log(f"[PREVIEW] Will align: idx={idx}, file={img_file.name}, focal={current_focal}")
                files_to_align.append((idx, img_file, current_focal))
        
        if files_to_align:
            log(f"[PREVIEW] Aligning {len(files_to_align)} images...")
            for i, (idx, img_file, focal) in enumerate(files_to_align):
                self.align_single_image(idx, img_file, focal)
            log("[PREVIEW] Done preparing previews")
        else:
            log(f"[PREVIEW] Using cached previews ({len(self.image_files)} images)")
    
    def align_single_image(self, idx, img_file, focal):
        if focal is None:
            img = cv2.imread(str(img_file))
            if img is not None:
                h, w = img.shape[:2]
                focal = (w / 2, h / 2)
            else:
                return
        
        if self.alignment_mode == "landscape":
            target_w, target_h = 2560, 1440
        else:
            target_w, target_h = 1440, 2560
        
        img = cv2.imread(str(img_file))
        if img is None:
            return
        
        h, w = img.shape[:2]
        focal_x, focal_y = focal
        
        crop_x, crop_y, scale, crop_w, crop_h = calculate_transformation(
            focal_x, focal_y, w, h, target_w, target_h
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
        
        output_name = f"{idx + 1:04d}.jpg"
        output_path = self.preview_folder / output_name
        cv2.imwrite(str(output_path), aligned, [cv2.IMWRITE_JPEG_QUALITY, 90])
        
        self.preview_state[img_file.name] = {"focal": [focal_x, focal_y], "aligned": True}
    
    def get_aligned_preview_path(self, idx):
        if self.alignment_mode is None:
            return None
        filename = f"{idx + 1:04d}.jpg"
        preview_path = self.preview_folder / filename
        if preview_path.exists():
            return preview_path
        return None

def show_processing_window(message="Processing..."):
    dialog_width = 500
    dialog_height = 200
    dialog_x = (DISPLAY_WIDTH - dialog_width) // 2
    dialog_y = (DISPLAY_HEIGHT - dialog_height) // 2
    
    display = np.zeros((DISPLAY_HEIGHT, DISPLAY_WIDTH, 3), dtype=np.uint8)
    display[:, :] = (25, 25, 25)
    
    cv2.rectangle(display, (dialog_x, dialog_y), (dialog_x + dialog_width, dialog_y + dialog_height), (50, 50, 50), -1)
    cv2.rectangle(display, (dialog_x, dialog_y), (dialog_x + dialog_width, dialog_y + dialog_height), (100, 100, 100), 3)
    
    cv2.putText(display, message,
                (dialog_x + dialog_width // 2 - 120, dialog_y + 80),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
    
    bar_width = 300
    bar_height = 20
    bar_x = dialog_x + (dialog_width - bar_width) // 2
    bar_y = dialog_y + 120
    
    cv2.rectangle(display, (bar_x, bar_y), (bar_x + bar_width, bar_y + bar_height), (30, 30, 30), -1)
    
    import time
    start_time = time.time()
    while True:
        elapsed = time.time() - start_time
        progress = (elapsed % 2.0) / 2.0
        
        progress_bar = display.copy()
        bar_fill = int(bar_width * progress)
        cv2.rectangle(progress_bar, (bar_x, bar_y), (bar_x + bar_fill, bar_y + bar_height), (0, 150, 0), -1)
        
        cv2.imshow(WINDOW_NAME, progress_bar)
        cv2.waitKey(50)
        
        yield


def run_transform(input_folder, orientation="landscape"):
    import subprocess
    import threading
    
    if orientation == "portrait":
        orient_text = "Portrait"
        orient_suffix = "_portrait"
    else:
        orient_text = "Landscape"
        orient_suffix = "_landscape"
    
    output_folder = str(Path(input_folder).parent / f"{Path(input_folder).name}_aligned_v2{orient_suffix}")
    
    cmd = [
        "python", "align_and_scale_images.py", 
        str(input_folder),
        "--output", output_folder,
        "--orientation", orientation
    ]
    
    print(f"\nRunning transformation script ({orient_text})...")
    print(f"Output folder: {output_folder}")
    
    cv2.destroyAllWindows()
    
    dialog_width = 500
    dialog_height = 200
    dialog_x = (DISPLAY_WIDTH - dialog_width) // 2
    dialog_y = (DISPLAY_HEIGHT - dialog_height) // 2
    
    import time
    start_time = time.time()
    
    def update_progress():
        while not done[0]:
            elapsed = time.time() - start_time
            progress = (elapsed % 2.0) / 2.0
            
            display = np.zeros((DISPLAY_HEIGHT, DISPLAY_WIDTH, 3), dtype=np.uint8)
            display[:, :] = (25, 25, 25)
            
            cv2.rectangle(display, (dialog_x, dialog_y), (dialog_x + dialog_width, dialog_y + dialog_height), (50, 50, 50), -1)
            cv2.rectangle(display, (dialog_x, dialog_y), (dialog_x + dialog_width, dialog_y + dialog_height), (100, 100, 100), 3)
            
            cv2.putText(display, f"Transforming ({orient_text})...",
                        (dialog_x + dialog_width // 2 - 150, dialog_y + 70),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
            
            cv2.putText(display, f"Output: {Path(output_folder).name}",
                        (dialog_x + dialog_width // 2 - 100, dialog_y + 100),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180, 180, 180), 1)
            
            bar_width = 300
            bar_height = 20
            bar_x = dialog_x + (dialog_width - bar_width) // 2
            bar_y = dialog_y + 130
            
            cv2.rectangle(display, (bar_x, bar_y), (bar_x + bar_width, bar_y + bar_height), (30, 30, 30), -1)
            
            bar_fill = int(bar_width * progress)
            cv2.rectangle(display, (bar_x, bar_y), (bar_x + bar_fill, bar_y + bar_height), (0, 180, 0), -1)
            
            cv2.imshow(WINDOW_NAME, display)
            cv2.waitKey(50)
    
    done = [False]
    progress_thread = threading.Thread(target=update_progress)
    progress_thread.start()
    
    result = subprocess.run(cmd, capture_output=False)
    
    done[0] = True
    progress_thread.join()
    
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(WINDOW_NAME, lambda *args: None)
    
    return result.returncode


def main():
    parser = argparse.ArgumentParser(
        description="Interactive focal point alignment tool"
    )
    parser.add_argument("input_folder", help="Path to folder containing images")
    parser.add_argument(
        "--output", "-o",
        help="Output folder path (default: input_folder_aligned)"
    )
    parser.add_argument(
        "--transform-only",
        action="store_true",
        help="Skip focal point aligner, go directly to transform"
    )
    parser.add_argument(
        "--orientation",
        choices=["landscape", "portrait"],
        default="landscape",
        help="Orientation for transformation (default: landscape)"
    )
    args = parser.parse_args()
    
    input_path = Path(args.input_folder)
    if not input_path.exists() or not input_path.is_dir():
        print(f"Error: {input_path} is not a valid directory")
        return 1
    
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = input_path.parent / f"{input_path.name}_aligned"
    
    if args.transform_only:
        return run_transform(input_path, args.orientation)
    
    try:
        while True:
            aligner = FocalPointAligner(input_path, output_path)
            result = aligner.run()
            
            if result == "transform_landscape":
                run_transform(input_path, "landscape")
                print("\nReturning to Focal Point Aligner...")
                continue
            elif result == "transform_portrait":
                run_transform(input_path, "portrait")
                print("\nReturning to Focal Point Aligner...")
                continue
            else:
                return result
    except ValueError as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    exit(main())
