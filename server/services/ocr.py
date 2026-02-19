import os
import tempfile

from PIL import Image
import pytesseract


def ocr_image_file(file_obj):
    """Run OCR on an uploaded image file and return extracted text."""
    with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as tmp:
        file_obj.save(tmp.name)
        image = Image.open(tmp.name)
        text = pytesseract.image_to_string(image, lang='deu+eng')
        os.unlink(tmp.name)
    return text
