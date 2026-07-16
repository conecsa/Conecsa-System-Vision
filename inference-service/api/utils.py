"""
Utilities for loading labels/classes and class-color management.
"""
import colorsys
import re

HEX_COLOR_RE = re.compile(r'^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$')


def load_class_labels(config):
    """
    Loads class labels from configuration files.

    Args:
        config: Config class instance

    Returns:
        list: List of class labels
    """
    # Try loading custom classes file first
    try:
        with open(config.CLASSES_FILE_PATH, "r") as f:
            labels = [line.strip() for line in f.readlines() if line.strip()]
            return labels
    except FileNotFoundError:
        return config.DEFAULT_LABELS


def generate_colors(num_classes):
    """
    Generates unique colors for each class.
    Supports unlimited number of classes using HSV for distinct colors.
    """
    # Predefined base colors for the first classes
    base_colors = [
        (0, 165, 255),   # Orange
        (0, 0, 255),     # Red
        (255, 0, 0),     # Blue
        (0, 255, 0),     # Green
        (255, 255, 0),   # Cyan
        (255, 0, 255),   # Magenta
        (0, 255, 255),   # Yellow
        (128, 0, 128),   # Purple
        (255, 165, 0),   # Light Orange
        (0, 128, 128),   # Teal
    ]

    colors = base_colors.copy()

    # For any additional number of classes, generate colors using HSV
    # This ensures well-distributed and visually distinct colors
    if num_classes > len(base_colors):
        additional_colors_needed = num_classes - len(base_colors)
        for i in range(additional_colors_needed):
            # Distribute evenly across the hue spectrum
            hue = (i / additional_colors_needed) % 1.0
            saturation = 0.8 + (i % 3) * 0.1  # Varies between 0.8 and 1.0
            value = 0.9 + (i % 2) * 0.1       # Varies between 0.9 and 1.0

            # Convert HSV to RGB
            rgb = colorsys.hsv_to_rgb(hue, saturation, value)
            bgr = (int(rgb[2] * 255), int(rgb[1] * 255), int(rgb[0] * 255))
            colors.append(bgr)

    return colors[:num_classes]


def hex_to_bgr(color_hex):
    """
    Convert hex color (#RGB or #RRGGBB) to OpenCV BGR tuple.
    """
    if len(color_hex) == 4:
        r = int(color_hex[1] * 2, 16)
        g = int(color_hex[2] * 2, 16)
        b = int(color_hex[3] * 2, 16)
    else:
        r = int(color_hex[1:3], 16)
        g = int(color_hex[3:5], 16)
        b = int(color_hex[5:7], 16)
    return b, g, r


def bgr_to_hex(bgr):
    """
    Convert an OpenCV BGR tuple to a "#rrggbb" string (inverse of hex_to_bgr).
    """
    b, g, r = bgr
    return "#{:02x}{:02x}{:02x}".format(int(r), int(g), int(b))


def parse_label_and_color(raw_label):
    """
    Parse labels in the format "class_name #hex".

    Returns:
        tuple[str, tuple|None]: (label_name, bgr_color_or_none)
    """
    text = (raw_label or "").strip()
    if not text:
        return "", None

    parts = text.rsplit(None, 1)
    if len(parts) == 2 and HEX_COLOR_RE.match(parts[1]):
        return parts[0].strip(), hex_to_bgr(parts[1])

    return text, None


def resolve_class_colors(class_labels):
    """
    Split raw class entries into names and BGR colors.

    Each entry is "name" or "name #hex". A name with no hex falls back to its
    slot in the generated palette, so the color is stable per class index.

    Returns:
        tuple[list[str], list[tuple]]: (names, bgr_colors)
    """
    names = []
    custom_colors = []
    for raw_label in class_labels:
        label_name, label_color = parse_label_and_color(raw_label)
        names.append(label_name if label_name else "Object")
        custom_colors.append(label_color)

    generated = generate_colors(len(names))
    colors = [
        custom if custom is not None else generated[idx]
        for idx, custom in enumerate(custom_colors)
    ]
    return names, colors
