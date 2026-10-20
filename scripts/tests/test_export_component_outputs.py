"""Synthetic settings and mocked process only; no .env reads or database access."""
import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('export_outputs', Path(__file__).parents[1] / 'export_component_outputs.py')
exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exporter)


class ExportTests(unittest.TestCase):
    def run_export(self, args, settings, returncode=0):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(exporter, 'REPO_ROOT', Path(directory)), \
                 patch.object(exporter.shutil, 'which', return_value='/synthetic/pg_dump'), \
                 patch('dotenv.dotenv_values', return_value=settings) as loader, \
                 patch.dict(exporter.os.environ, {}, clear=True), \
                 patch.object(exporter.subprocess, 'run') as run, \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                run.return_value.returncode = returncode
                result = exporter.main(args)
                return result, run.call_args, output.getvalue(), loader.call_args

    def test_default_credentials_are_not_command_arguments_or_console_output(self):
        settings = {'APP_DB_PFOI_USER': 'synthetic_owner', 'APP_DB_PFOI_PASSWORD': 'fictional_$secret'}
        result, call, output, loader = self.run_export([], settings)
        self.assertEqual(result, 0)
        self.assertIn('--schema=c1_output', call.args[0])
        self.assertNotIn(settings['APP_DB_PFOI_PASSWORD'], ' '.join(call.args[0]) + output)
        self.assertEqual(call.kwargs['env']['PGPASSWORD'], settings['APP_DB_PFOI_PASSWORD'])
        self.assertIn('component_exports', call.args[0][-1])
        self.assertFalse(loader.kwargs['interpolate'])

    def test_other_component_uses_its_own_settings_and_schema(self):
        result, call, _, _ = self.run_export(['--schema', 'c3_output', '--env-prefix', 'APP_DB_C3'],
            {'APP_DB_C3_USER': 'synthetic_owner', 'APP_DB_C3_PASSWORD': 'fictional'})
        self.assertEqual(result, 0)
        self.assertIn('--schema=c3_output', call.args[0])

    def test_missing_credentials_do_not_start_process(self):
        result, call, _, _ = self.run_export([], {})
        self.assertEqual(result, 1)
        self.assertIsNone(call)

    def test_failure_does_not_print_database_diagnostics(self):
        result, _, output, _ = self.run_export([], {'APP_DB_PFOI_USER': 'synthetic', 'APP_DB_PFOI_PASSWORD': 'fictional'}, 1)
        self.assertEqual(result, 1)
        self.assertIn('incomplete', output)
        self.assertNotIn('fictional', output)


if __name__ == '__main__':
    unittest.main()
