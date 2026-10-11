import argparse
from pathlib import Path
from urllib.parse import urlsplit

import qrcode
from PIL import Image, ImageDraw, ImageFont

PUBLIC_URL = "https://your-inbox.example.com"


def generate(destination, public_url=PUBLIC_URL):
    url = urlsplit(public_url)
    if url.scheme != "https" or not url.hostname or url.username or url.query or url.fragment:
        raise ValueError("Use the public HTTPS upload page URL without credentials or query.")
    destination.mkdir(parents=True, exist_ok=True)
    code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=14, border=4)
    code.add_data(public_url)
    code.make(fit=True)
    qr = code.make_image(fill_color="black", back_color="white").convert("RGB")
    qr.save(destination / "qr.png", dpi=(300, 300))
    poster = Image.new("RGB", (1181, 1772), "white")  # 10 x 15 cm at 300 dpi.
    draw = ImageDraw.Draw(poster)

    def font(size, bold=False):
        name = "arialbd.ttf" if bold else "arial.ttf"
        path = Path("C:/Windows/Fonts") / name
        return (
            ImageFont.truetype(str(path), size)
            if path.exists()
            else ImageFont.load_default(size=size)
        )

    draw.text((590, 190), "Dosyanızı seçin.", fill="black", anchor="mm", font=font(72, True))
    draw.text((590, 285), "Doğrudan aktarın.", fill="black", anchor="mm", font=font(72, True))
    draw.text((590, 420), "Kameranızı QR koda tutun.", fill="black", anchor="mm", font=font(38))
    poster.paste(qr, ((1181 - qr.width) // 2, 550))
    draw.text(
        (590, 1390), "Dosyalarınızı seçin ve gönderin.", fill="black", anchor="mm", font=font(38)
    )
    draw.text(
        (590, 1450), "Gönderim numaranızı kaydedin.", fill="black", anchor="mm", font=font(38)
    )
    draw.text(
        (590, 1600),
        "PDF · Word · Excel · PowerPoint · JPG · PNG",
        fill="black",
        anchor="mm",
        font=font(27),
    )
    poster.save(destination / "qr-poster.png", dpi=(300, 300))
    return qr, poster


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True, help="Your public HTTPS upload page")
    parser.add_argument("--output", type=Path, default=Path("dist/qr"))
    args = parser.parse_args()
    generate(args.output, args.url)
    print("QR ready in " + str(args.output))
