"""
Overlay renderer - Renders status overlays on video frames.
"""
# noinspection PyPackageRequirements
import numpy as np # Package is included on os build.

# noinspection PyPackageRequirements
import cv2 # Package is included on os build.

from typing import Tuple


class OverlayRenderer:
    """Class for rendering status overlays on video frames."""

    @staticmethod
    def _calculate_overlay_position(width: int, height: int,
                                    box_width: int, box_height: int,
                                    position: str = "top-right") -> Tuple[int, int, int, int, int, int]:
        """
        Calculate overlay box and text positions.

        Args:
            width: Image width
            height: Image height
            box_width: Width of overlay box
            box_height: Height of overlay box
            position: Position of overlay ("top-right", "top-left", "bottom-left", "bottom-right")

        Returns:
            Tuple of (box_x1, box_y1, box_x2, box_y2, text_x, text_y)
        """
        text_padding = 5

        if position == "top-right":
            box_x1 = width - box_width
            box_y1 = 0
            box_x2 = width
            box_y2 = box_height
            text_x = box_x1 + text_padding
            text_y = box_height - 15
        elif position == "top-left":
            box_x1 = 0
            box_y1 = 0
            box_x2 = box_width
            box_y2 = box_height
            text_x = text_padding
            text_y = box_height - 15
        elif position == "bottom-left":
            box_x1 = 0
            box_y1 = height - box_height
            box_x2 = box_width
            box_y2 = height
            text_x = text_padding
            text_y = height - 10
        elif position == "bottom-right":
            box_x1 = width - box_width
            box_y1 = height - box_height
            box_x2 = width
            box_y2 = height
            text_x = box_x1 + text_padding
            text_y = height - 10
        else:  # Default to top-left
            box_x1 = 0
            box_y1 = 0
            box_x2 = box_width
            box_y2 = box_height
            text_x = text_padding
            text_y = box_height - 15

        return box_x1, box_y1, box_x2, box_y2, text_x, text_y

    @staticmethod
    def draw_detection_off_overlay(image: np.ndarray,
                                   position: str = "top-right") -> np.ndarray:
        """
        Draw "Detection Off" overlay when detection is not running.

        Args:
            image: Input image
            position: Position of overlay

        Returns:
            Image with overlay
        """
        height, width = image.shape[:2]
        box_x1, box_y1, box_x2, box_y2, text_x, text_y = OverlayRenderer._calculate_overlay_position(
            width, height, 150, 40, position
        )

        # Gray background
        cv2.rectangle(image, (box_x1, box_y1), (box_x2, box_y2), (128, 128, 128), -1)

        # White text
        cv2.putText(
            image,
            "Detection Off",
            (text_x, text_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (255, 255, 255),
            2
        )

        return image

