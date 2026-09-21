"""Image uploads keep the sender's quality: colour profile, JPEG compression
settings and pixels are preserved, private metadata is still stripped."""
import io
import os
import shutil
import tempfile
from unittest import mock

from django.test import SimpleTestCase
from PIL import Image, ImageCms, ImageChops, ImageOps, ImageStat, JpegImagePlugin

from media_assets.validation import THUMBNAIL_MAX_SIDE, validate_and_process_image

SRGB_ICC = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()


def natural_image(w=320, h=240):
    """Gradient plus noise, so compression settings visibly matter."""
    grad = Image.linear_gradient('L').resize((w, h))
    noise = Image.effect_noise((w, h), 14)
    r = ImageChops.add(grad, noise, scale=2)
    return Image.merge('RGB', (r, ImageOps.mirror(r), ImageOps.flip(r)))


class Base(SimpleTestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='fidelity_')
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def path(self, name):
        return os.path.join(self.dir, name)

    def write(self, image, name, **save_kwargs):
        p = self.path(name)
        image.save(p, **save_kwargs)
        return p

    def process(self, src):
        result = validate_and_process_image(src, self.path('processed'), self.path('thumb.jpg'))
        return result, Image.open(result.processed_path), Image.open(result.thumbnail_path)


def tables(im):
    return {k: list(v) for k, v in im.quantization.items()}


class JpegFidelityTests(Base):
    def test_the_senders_quantization_tables_are_reused_not_replaced_by_a_fixed_quality(self):
        for quality in (72, 88, 97):
            src = self.write(natural_image(), f'q{quality}.jpg', format='JPEG', quality=quality)
            _, out, _ = self.process(src)
            self.assertEqual(tables(out), tables(Image.open(src)), quality)

    def test_chroma_subsampling_is_preserved(self):
        for subsampling in (0, 2):
            src = self.write(natural_image(), f's{subsampling}.jpg', format='JPEG', quality=90, subsampling=subsampling)
            _, out, _ = self.process(src)
            self.assertEqual(JpegImagePlugin.get_sampling(out), subsampling)

    def test_pixels_are_practically_identical_to_the_original(self):
        src = self.write(natural_image(), 'p.jpg', format='JPEG', quality=90)
        _, out, _ = self.process(src)
        diff = ImageChops.difference(Image.open(src).convert('RGB'), out.convert('RGB'))
        self.assertLess(max(ImageStat.Stat(diff).mean), 1.5)

    def test_file_is_not_inflated(self):
        src = self.write(natural_image(640, 480), 'big.jpg', format='JPEG', quality=88)
        result, _, _ = self.process(src)
        self.assertLessEqual(os.path.getsize(result.processed_path), os.path.getsize(src) * 1.2)

    def test_dimensions_are_untouched(self):
        src = self.write(natural_image(1234, 777), 'dims.jpg', format='JPEG', quality=90)
        result, out, _ = self.process(src)
        self.assertEqual((result.width, result.height), (1234, 777))
        self.assertEqual(out.size, (1234, 777))

    def test_grayscale_jpeg_keeps_its_single_table(self):
        src = self.write(natural_image().convert('L'), 'g.jpg', format='JPEG', quality=85)
        _, out, _ = self.process(src)
        self.assertEqual(out.mode, 'L')
        self.assertEqual(tables(out), tables(Image.open(src)))

    def test_falls_back_to_high_fixed_quality_when_tables_cannot_be_reused(self):
        src = self.write(natural_image(), 'fb.jpg', format='JPEG', quality=90, icc_profile=SRGB_ICC)
        with mock.patch('PIL.JpegImagePlugin.get_sampling', return_value=-1):
            result, out, _ = self.process(src)
        self.assertEqual(out.format, 'JPEG')
        self.assertEqual(out.size, (320, 240))
        self.assertEqual(out.info.get('icc_profile'), SRGB_ICC)      # still colour-accurate on the fallback path
        self.assertEqual(result.mime_type, 'image/jpeg')


class ColourProfileTests(Base):
    def test_icc_profile_is_kept_on_jpeg(self):
        src = self.write(natural_image(), 'icc.jpg', format='JPEG', quality=90, icc_profile=SRGB_ICC)
        _, out, thumb = self.process(src)
        self.assertEqual(out.info.get('icc_profile'), SRGB_ICC)
        self.assertEqual(thumb.info.get('icc_profile'), SRGB_ICC)

    def test_icc_profile_is_kept_on_png_and_webp(self):
        png = self.write(natural_image(), 'icc.png', format='PNG', icc_profile=SRGB_ICC)
        _, out, _ = self.process(png)
        self.assertEqual(out.info.get('icc_profile'), SRGB_ICC)
        webp = self.write(natural_image(), 'icc.webp', format='WEBP', quality=90, icc_profile=SRGB_ICC)
        _, out, _ = self.process(webp)
        self.assertEqual(out.info.get('icc_profile'), SRGB_ICC)

    def test_image_without_a_profile_gets_none_added(self):
        src = self.write(natural_image(), 'plain.jpg', format='JPEG', quality=90)
        _, out, _ = self.process(src)
        self.assertNotIn('icc_profile', out.info)


class PngIsLossless(Base):
    def test_png_pixels_and_alpha_are_identical(self):
        rgba = natural_image().convert('RGBA')
        rgba.putalpha(Image.linear_gradient('L').resize(rgba.size))
        src = self.write(rgba, 'a.png', format='PNG')
        _, out, _ = self.process(src)
        self.assertEqual(out.mode, 'RGBA')
        self.assertIsNone(ImageChops.difference(Image.open(src), out).getbbox())      # bit-for-bit pixels


class PrivacyAndOrientationStillHold(Base):
    def exif_jpeg(self, size, orientation):
        exif = Image.Exif()
        exif[0x010F] = 'PrivateCameraMaker'
        exif[0x0110] = 'SecretModel'
        exif[0x0112] = orientation
        return self.write(natural_image(*size), 'exif.jpg', format='JPEG', quality=90, exif=exif)

    def test_exif_metadata_is_stripped(self):
        _, out, _ = self.process(self.exif_jpeg((320, 240), 1))
        self.assertEqual(len(out.getexif()), 0)
        self.assertNotIn(b'PrivateCameraMaker', open(out.filename, 'rb').read())

    def test_orientation_is_baked_into_the_pixels(self):
        result, out, _ = self.process(self.exif_jpeg((200, 100), 6))     # 6 = rotate 90 degrees
        self.assertEqual(out.size, (100, 200))
        self.assertEqual((result.width, result.height), (100, 200))
        self.assertNotIn(0x0112, out.getexif())


class ThumbnailTests(Base):
    def test_thumbnail_is_a_sharper_bounded_jpeg(self):
        src = self.write(natural_image(1600, 1200), 'big.jpg', format='JPEG', quality=90)
        _, out, thumb = self.process(src)
        self.assertEqual(thumb.format, 'JPEG')
        self.assertEqual(max(thumb.size), THUMBNAIL_MAX_SIDE)
        self.assertGreater(THUMBNAIL_MAX_SIDE, 320)
        self.assertEqual(out.size, (1600, 1200))                          # the full image is never shrunk

    def test_small_images_are_not_upscaled_into_thumbnails(self):
        src = self.write(natural_image(200, 150), 'small.jpg', format='JPEG', quality=90)
        _, _, thumb = self.process(src)
        self.assertEqual(thumb.size, (200, 150))
