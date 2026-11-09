import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError

from model_adapter import build_request, extract_candidates, generate
from run_model import load_settings


class ModelAdapterTests(unittest.TestCase):
    def test_dotenv_loading(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            path = Path(directory) / '.env'
            path.write_text('\ufeff# local settings\nGEMINI_API_KEY="synthetic"\nGEMINI_MODEL=test\n', encoding='utf-8')
            load_settings(path)
            self.assertEqual(os.environ['GEMINI_API_KEY'], 'synthetic')
            os.environ['GEMINI_MODEL'] = 'override'
            load_settings(path)
            self.assertEqual(os.environ['GEMINI_MODEL'], 'override')
            path.write_text('GEMINI_API_KEY=one\nGEMINI_API_KEY=two', encoding='utf-8')
            with self.assertRaises(ValueError):
                load_settings(path)

    def test_request_and_response(self):
        body = build_request({'id': 'synthetic'}, 'Synthetic contract')
        raw = json.dumps(dict(candidates=[dict(finishReason='STOP', content=dict(parts=[
            dict(text='internal', thought=True),
            dict(text='{"schema_version":1,"promos":[]}')]))], usageMetadata={'totalTokenCount': 10})).encode()
        response = MagicMock()
        response.__enter__.return_value.read.return_value = raw
        with patch('model_adapter.urlopen', return_value=response) as transport:
            self.assertEqual(generate('test-model', 'test-key', body), raw)
            request = transport.call_args.args[0]
            self.assertNotIn('test-key', request.full_url)
            self.assertEqual(json.loads(request.data), body)
        result, usage, version = extract_candidates(raw)
        self.assertEqual(result['promos'], [])
        self.assertEqual(usage['totalTokenCount'], 10)

    def test_incomplete_blocked_and_malformed_responses(self):
        for payload in [{}, {'candidates': [{'finishReason': 'MAX_TOKENS'}]},
                        {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': 'bad JSON'}]}}]}]:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                extract_candidates(json.dumps(payload))

    def test_credentials_and_http_failure(self):
        with self.assertRaises(ValueError):
            generate('test-model', '', {})
        with patch('model_adapter.urlopen', side_effect=HTTPError('https://example.com', 429, 'quota', {}, None)):
            with self.assertRaisesRegex(RuntimeError, 'HTTP 429'):
                generate('test-model', 'test-key', {})


if __name__ == '__main__':
    unittest.main()
