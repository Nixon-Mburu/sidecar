"""Build the small raster app mark; no external image assets are needed."""
from pathlib import Path
from PIL import Image, ImageDraw

image = Image.new('RGB', (512, 512), '#2455e8')
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((105, 139, 357, 322), radius=20, outline='white', width=18)
draw.line((181, 373, 282, 373), fill='white', width=18)
draw.line((230, 322, 230, 371), fill='white', width=18)
draw.rounded_rectangle((302, 228, 408, 385), radius=18, fill='#2455e8', outline='white', width=14)
draw.line((340, 355, 370, 355), fill='white', width=8)
image.save(Path(__file__).resolve().parent.parent / 'public/icon.png')
