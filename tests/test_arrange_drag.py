import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_DIR))

from aligner_core import FocalPointAlignerCore


def test_move_image_manual():
    """Manually test move_image without full AlignerCore initialization."""
    import tempfile
    import cv2
    import numpy as np
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        img_dir = tmp_path / 'test_images'
        img_dir.mkdir()
        
        for i in range(5):
            img = np.zeros((1080, 1920, 3), dtype=np.uint8)
            img[:, :] = (i * 50, i * 50, i * 50)
            cv2.imwrite(str(img_dir / f'image{i:04d}.jpg'), img)
        
        output_dir = tmp_path / 'output'
        output_dir.mkdir()
        
        config = {
            "input_folder": str(img_dir),
            "output_folder": str(output_dir)
        }
        
        core = FocalPointAlignerCore(config)
        for i in range(5):
            core.focal_points[i] = (960.0, 540.0)
            core.completed.add(i)
            core.auto_center_flags[i] = True
            core.image_dimensions[i] = (1920, 1080)
        
        print('BEFORE move_image(3, 1):')
        print(f'  images: {[p.name for p in core.image_files]}')
        print(f'  focal_points: {dict(core.focal_points)}')
        print(f'  completed: {core.completed}')
        print(f'  auto_center: {dict(core.auto_center_flags)}')
        
        result = core.move_image(3, 1)
        print(f'\nmove_image(3, 1) returned: {result}')
        
        print('\nAFTER:')
        print(f'  images: {[p.name for p in core.image_files]}')
        print(f'  focal_points: {dict(core.focal_points)}')
        print(f'  completed: {core.completed}')
        print(f'  auto_center: {dict(core.auto_center_flags)}')
        
        new_indices = sorted(core.focal_points.keys())
        print(f'\nFocal point indices: {new_indices}')
        
        if new_indices == [0, 1, 2, 3, 4]:
            print('SUCCESS: Indices correctly shifted')
        else:
            print(f'FAIL: Expected [0,1,2,3,4], got {new_indices}')
        
        expected = [(960, 540)] * 5
        actual = [core.focal_points.get(i) for i in range(5)]
        if actual == expected:
            print('SUCCESS: Focal points aligned to correct images')
        else:
            print(f'FAIL: Focal points misaligned. Expected {expected}, got {actual}')


if __name__ == '__main__':
    test_move_image_manual()