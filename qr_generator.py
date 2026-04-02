# qr_generator.py  (корень проекта)
import io
import qrcode
from PIL import Image

BRAND_COLOR = (100, 18, 18)   # #641212
LOGO_PATH   = "logo.png"      # лежит в корне проекта


def generate_qr_bytes(barcode: str) -> bytes:
    qr = qrcode.QRCode(
        version=6,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=16,
        border=3,
    )
    qr.add_data(barcode)
    qr.make(fit=True)

    img = qr.make_image(fill_color=BRAND_COLOR, back_color=(255, 255, 255)).convert("RGBA")

    try:
        logo = Image.open(LOGO_PATH).convert("RGBA")
        qr_w, qr_h = img.size
        logo_size = int(qr_w * 0.25)
        logo = logo.resize((logo_size, logo_size), Image.LANCZOS)

        pad = 14
        bg_size = logo_size + pad * 2
        bg = Image.new("RGBA", (bg_size, bg_size), (255, 255, 255, 255))
        pos_bg = ((qr_w - bg_size) // 2, (qr_h - bg_size) // 2)
        img.paste(bg, pos_bg, mask=bg)

        pos_logo = ((qr_w - logo_size) // 2, (qr_h - logo_size) // 2)
        img.paste(logo, pos_logo, mask=logo.split()[3])
    except Exception:
        pass

    final = Image.new("RGB", img.size, (255, 255, 255))
    final.paste(img, mask=img.split()[3])

    buf = io.BytesIO()
    final.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf.getvalue()
