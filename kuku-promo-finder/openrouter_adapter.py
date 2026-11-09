"""OpenRouter calls with a persistent, conservative project spending budget."""

from contextlib import contextmanager
from decimal import Decimal
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4


MODEL = 'google/gemini-2.5-flash-lite'
BUDGET = Path(__file__).parent / 'local_data' / 'openrouter_budget.json'
CEILING = Decimal('0.90')
# Entire 1,048,576-token context at $0.10/M plus 2,048 output tokens
# at $0.40/M costs $0.1056768. $0.12 includes an additional buffer.
RESERVE = Decimal('0.12')


@contextmanager
def budget_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix('.lock')
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError('Budget is locked by another run. Check it before retrying.') from None
    try:
        yield
    finally:
        os.close(descriptor)
        lock.unlink()


def reserve_budget(path=BUDGET):
    with budget_lock(path):
        data = json.loads(path.read_text()) if path.exists() else dict(entries=[])
        if data.get('billing_anomaly'):
            raise RuntimeError('Budget stopped after unexpected billing')
        total = sum((Decimal(entry['charged_or_reserved_usd']) for entry in data['entries']), Decimal(0))
        if total + RESERVE > CEILING:
            raise RuntimeError('Project budget cannot cover another request; no paid request sent')
        identifier = uuid4().hex
        data['entries'].append(dict(id=identifier, status='reserved', charged_or_reserved_usd=str(RESERVE)))
        write_budget(path, data)
        return identifier


def write_budget(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def settle_budget(identifier, cost, path=BUDGET):
    if cost is None:
        return  # Unknown or timed-out charges keep the entire reservation.
    amount = Decimal(str(cost))
    if not amount.is_finite() or amount < 0:
        return
    with budget_lock(path):
        data = json.loads(path.read_text())
        entry = next(entry for entry in data['entries'] if entry['id'] == identifier)
        entry.update(status='reported', charged_or_reserved_usd=str(amount))
        if amount > RESERVE:
            # Unexpected billing invalidates our bound. Stop all future calls.
            data['billing_anomaly'] = True
        write_budget(path, data)


def build_body(request):
    return dict(model=MODEL, messages=[
        dict(role='system', content=request['systemInstruction']['parts'][0]['text']),
        dict(role='user', content=request['contents'][0]['parts'][0]['text'])],
        max_tokens=2048, response_format=dict(type='json_object'),
        reasoning=dict(enabled=False),
        provider=dict(max_price=dict(prompt=0.10, completion=0.40, request=0), require_parameters=True))


def generate(api_key, body, raw_path, timeout=120):
    if not api_key.strip():
        raise ValueError('LLM_API_KEY is missing')
    # Restrict this adapter to the priced and bounded model configuration.
    if body['model'] != MODEL or body['max_tokens'] != 2048:
        raise ValueError('Unsupported configuration for the project budget')
    if BUDGET.exists() and json.loads(BUDGET.read_text()).get('billing_anomaly'):
        raise RuntimeError('Budget stopped after unexpected billing')
    identifier = reserve_budget()
    request = Request('https://openrouter.ai/api/v1/chat/completions',
                      data=json.dumps(body).encode('utf-8'),
                      headers={'Authorization': 'Bearer ' + api_key, 'Content-Type': 'application/json'},
                      method='POST')
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
        raw_path.write_bytes(raw)
        result = json.loads(raw)
        settle_budget(identifier, result.get('usage', {}).get('cost'))
        return raw
    except HTTPError as error:
        raise RuntimeError(f'OpenRouter HTTP {error.code}. Reservation retained; no automatic retry.') from None
    except (URLError, TimeoutError):
        raise RuntimeError('OpenRouter connection failed. Reservation retained; no automatic retry.') from None


def extract_candidates(raw):
    response = json.loads(raw)
    choices = response.get('choices', [])
    if not choices or choices[0].get('finish_reason') != 'stop':
        raise ValueError('OpenRouter returned no complete candidate; inspect raw response')
    content = choices[0].get('message', {}).get('content')
    if not isinstance(content, str):
        raise ValueError('OpenRouter returned no text')
    return json.loads(content), response.get('usage', {}), response.get('model')
