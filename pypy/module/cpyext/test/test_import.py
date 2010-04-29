from pypy.module.cpyext.test.test_api import BaseApiTest
from pypy.module.cpyext.test.test_cpyext import AppTestCpythonExtensionBase

class TestImport(BaseApiTest):
    def setup_method(self, func):
        from pypy.module.imp.importing import importhook
        importhook(self.space, "os") # warm up reference counts
        BaseApiTest.setup_method(self, func)

    def test_import(self, space, api):
        pdb = api.PyImport_Import(space.wrap("pdb"))
        assert pdb
        assert space.getattr(pdb, space.wrap("pm"))

class AppTestImportLogic(AppTestCpythonExtensionBase):
    def test_import_logic(self):
        path = self.import_module(name='test_import_module', load_it=False)
        import sys
        sys.path.append(path)
        import test_import_module
        assert test_import_module.TEST is None

