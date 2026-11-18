import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class HeadlessRenderBackend(unittest.TestCase):
    """`GONGYU_HEADLESS` must not imply software rendering.

    The default (phase123) behaviour is pinned first: an unset GONGYU_RENDER_GPU has
    to pop the d3d12 adapter exactly as before.  Only the explicit opt-in keeps it.
    """

    KEYS = ("MESA_LOADER_DRIVER_OVERRIDE", "GALLIUM_DRIVER",
            "MESA_D3D12_DEFAULT_ADAPTER_NAME")

    def _env(self, out, **overrides):
        import os
        import tempfile
        from pathlib import Path
        from ros import fleet_runner
        saved = dict(os.environ)
        for key in ("GONGYU_HEADLESS", "GONGYU_RENDER_GPU"):
            os.environ.pop(key, None)
        os.environ.update(overrides)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                return fleet_runner.environment_for(tmp, Path(out))
        finally:
            os.environ.clear()
            os.environ.update(saved)

    def test_headless_default_still_pops_gpu_backend(self):
        env = self._env("out-default", GONGYU_HEADLESS="1")
        for key in self.KEYS:
            self.assertNotIn(key, env)

    def test_headless_with_render_gpu_keeps_backend(self):
        env = self._env("out-gpu", GONGYU_HEADLESS="1", GONGYU_RENDER_GPU="1")
        self.assertEqual(env.get("GALLIUM_DRIVER"), "d3d12")
        self.assertEqual(env.get("MESA_D3D12_DEFAULT_ADAPTER_NAME"), "NVIDIA")

    def test_gui_keeps_backend(self):
        env = self._env("out-gui")
        self.assertEqual(env.get("GALLIUM_DRIVER"), "d3d12")
