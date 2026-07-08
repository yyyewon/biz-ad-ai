from PIL import Image

from app.utils.image_bytes import (
    bytes_to_named_file,
    decode_base64_to_image_bytes,
    encode_image_bytes_to_base64,
    image_bytes_to_pil,
    pil_image_to_png_bytes,
)


def test_encode_and_decode_image_bytes_round_trip():
    image = Image.new("RGB", (16, 16), "white")
    image_bytes = pil_image_to_png_bytes(image)

    encoded = encode_image_bytes_to_base64(image_bytes)
    decoded = decode_base64_to_image_bytes(encoded)

    assert decoded == image_bytes


def test_decode_base64_supports_data_url_prefix():
    image = Image.new("RGB", (16, 16), "white")
    image_bytes = pil_image_to_png_bytes(image)

    encoded = encode_image_bytes_to_base64(image_bytes)
    decoded = decode_base64_to_image_bytes(f"data:image/png;base64,{encoded}")

    assert decoded == image_bytes


def test_image_bytes_to_pil():
    image = Image.new("RGB", (16, 16), "white")
    image_bytes = pil_image_to_png_bytes(image)

    result = image_bytes_to_pil(image_bytes)

    assert result.size == (16, 16)


def test_bytes_to_named_file_has_name():
    image = Image.new("RGB", (16, 16), "white")
    image_bytes = pil_image_to_png_bytes(image)

    file_obj = bytes_to_named_file(image_bytes, filename="source.png")

    assert file_obj.name == "source.png"
    assert file_obj.read() == image_bytes
