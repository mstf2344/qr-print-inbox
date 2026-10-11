import zxingcpp

from scripts.make_qr import PUBLIC_URL, generate


def test_qr_and_poster_decode_to_the_exact_public_address(tmp_path):
    qr, poster = generate(tmp_path)
    assert zxingcpp.read_barcode(qr).text == PUBLIC_URL
    assert zxingcpp.read_barcode(poster).text == PUBLIC_URL
    assert zxingcpp.read_barcode(poster.resize((394, 591))).text == PUBLIC_URL


def test_custom_owner_address(tmp_path):
    address = "https://my-shop.my-account.workers.dev"
    qr, poster = generate(tmp_path, address)
    assert zxingcpp.read_barcode(qr).text == address
    assert zxingcpp.read_barcode(poster).text == address
