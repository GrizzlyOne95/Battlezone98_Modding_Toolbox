import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from bztoolbox.modules.world.world_builder_core import BZ98TRNArchitect


class SkyCreatorImportTests(unittest.TestCase):
    def creator(self):
        app = BZ98TRNArchitect.__new__(BZ98TRNArchitect)
        app.stock_time = Mock()
        app.light_ambient = [Mock() for _ in range(3)]
        app.light_diffuse = [Mock() for _ in range(3)]
        app.log = Mock()
        return app

    def test_binary_source_populates_controls_without_rounding_to_slider_steps(self):
        payload = bytearray(212)
        struct.pack_into('<7f',payload,0,.4,.5,.1,1,-50,450,500)
        struct.pack_into('<2f',payload,28,24,8)
        struct.pack_into('<4f',payload,44,1,100/255,20/255,1)
        struct.pack_into('<4f',payload,60,15/255,50/255,5/255,1)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'source.sky'
            path.write_bytes(struct.pack('<III',0x534B595F,4,0x10000)
                             + struct.pack('<II',0x534B5931,len(payload)) + payload)
            app = self.creator()
            with patch('bztoolbox.modules.world.world_builder_core.filedialog.askopenfilename',return_value=str(path)):
                app.load_source_sky_lighting()
            app.stock_time.set.assert_called_once_with(800)
            for variables,values in ((app.light_diffuse,(1,100/255,20/255)),
                                     (app.light_ambient,(15/255,50/255,5/255))):
                for variable,value in zip(variables,values):
                    self.assertAlmostEqual(variable.set.call_args.args[0],value,places=7)

    def test_invalid_file_leaves_all_controls_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'bad.sky';path.write_bytes(b'invalid')
            app = self.creator()
            with patch('bztoolbox.modules.world.world_builder_core.filedialog.askopenfilename',return_value=str(path)), \
                 patch('bztoolbox.modules.world.world_builder_core.messagebox.showerror') as error:
                app.load_source_sky_lighting()
            error.assert_called_once()
            for variable in [app.stock_time,*app.light_ambient,*app.light_diffuse]:
                variable.set.assert_not_called()
