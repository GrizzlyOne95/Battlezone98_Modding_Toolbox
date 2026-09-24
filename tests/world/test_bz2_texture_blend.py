import unittest

import numpy as np

from bztoolbox.modules.world.bz2_texture_blend import blend_rgb_u8, sequential_layer_weights


class BZ2TextureBlendTests(unittest.TestCase):
    def test_zero_alphas_are_entirely_layer_zero(self):
        alphas = np.zeros((3, 2, 3), dtype=np.uint8)
        weights = sequential_layer_weights(alphas)
        self.assertTrue(np.all(weights[0] == 1.0))
        self.assertTrue(np.all(weights[1:] == 0.0))

    def test_sequential_weights_match_closed_form(self):
        alphas = np.array([[[128]], [[64]], [[192]]], dtype=np.uint8)
        weights = sequential_layer_weights(alphas)[:, 0, 0]
        a1, a2, a3 = 128 / 255.0, 64 / 255.0, 192 / 255.0
        expected = np.array([
            (1-a1) * (1-a2) * (1-a3),
            a1 * (1-a2) * (1-a3),
            a2 * (1-a3),
            a3,
        ])
        np.testing.assert_allclose(weights, expected, rtol=1e-6, atol=1e-7)
        self.assertAlmostEqual(float(weights.sum()), 1.0, places=6)

    def test_later_fully_opaque_layer_erases_lower_layers(self):
        alphas = np.array([[[200]], [[255]], [[0]]], dtype=np.uint8)
        weights = sequential_layer_weights(alphas)[:, 0, 0]
        np.testing.assert_allclose(weights, [0.0, 0.0, 1.0, 0.0])

        alphas[2, 0, 0] = 255
        weights = sequential_layer_weights(alphas)[:, 0, 0]
        np.testing.assert_allclose(weights, [0.0, 0.0, 0.0, 1.0])

    def test_integer_color_blend_matches_layer_order_and_truncation(self):
        colors = [
            (255, 0, 0),
            (0, 255, 0),
            (0, 0, 255),
            (255, 255, 0),
        ]
        result = blend_rgb_u8(colors, (128, 64, 192))

        current = np.array(colors[0], dtype=np.int64)
        for color, alpha in zip(colors[1:], (128, 64, 192)):
            current = (
                np.array(color, dtype=np.int64) * alpha
                + current * (255 - alpha)
            ) // 255
        self.assertEqual(result, tuple(int(v) for v in current))

    def test_invalid_alpha_shape_and_range_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "shape"):
            sequential_layer_weights(np.zeros((4, 1, 1), dtype=np.uint8))
        with self.assertRaisesRegex(ValueError, "range"):
            sequential_layer_weights(np.array([[[0]], [[0]], [[256]]], dtype=np.int16))


if __name__ == "__main__":
    unittest.main()
