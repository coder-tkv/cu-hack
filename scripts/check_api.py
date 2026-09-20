"""Exercise the running Docker stack over HTTP; no paid ML calls."""

import argparse
import json
import time
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from zipfile import ZipFile


def request(base, path, data=None, headers=None):
    try:
        with urlopen(Request(base + path, data=data, headers=headers or {}), timeout=30) as response:
            return response.status, response.read()
    except HTTPError as exc:
        return exc.code, exc.read()


def upload(base, content):
    boundary = uuid.uuid4().hex
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="llm_enabled"\r\n\r\nfalse\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="session.jsonl"\r\n'
            'Content-Type: application/octet-stream\r\n\r\n').encode()
    return request(base, '/api/sessions', body + content + f'\r\n--{boundary}--\r\n'.encode(),
                   {'Content-Type': f'multipart/form-data; boundary={boundary}'})


def analyze(base, content):
    status, body = upload(base, content)
    assert status == 202, f'Upload returned {status}'
    created = json.loads(body)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        code, body = request(base, created['status_url'])
        assert code == 200
        state = json.loads(body)
        if state['status'] in ('complete', 'partial', 'insufficient_data'):
            break
        assert state['status'] not in ('failed', 'interrupted'), state.get('error')
        time.sleep(0.1)
    else:
        raise AssertionError('Analysis exceeded 120 seconds')
    code, body = request(base, created['status_url'] + '/report')
    assert code == 200
    report = json.loads(body)
    assert report['session_id'] == created['session_id']
    assert report['provenance']['model'] is None
    assert report['ml_details'] is None
    assert report['provenance']['parser_version'] != 'mock-v0'
    for artifact in report['artifacts']:
        code, data = request(base, created['status_url'] + '/artifacts/' + artifact)
        assert code == 200 and data
        if artifact == 'report.json':
            assert json.loads(data) == report
    code, _ = request(base, created['status_url'] + '/artifacts/not-allowed.txt')
    assert code == 400
    for finding in report['findings']:
        for sid in finding['evidence_step_ids'][:1]:
            code, body = request(base, '/api/sessions/' + created['session_id'] + '/steps/' + sid)
            assert code == 200 and json.loads(body)['step']['step_id'] == sid
            assert request(base, '/api/sessions/another-session/steps/' + sid)[0] == 404
    code, body = request(base, '/api/sessions/' + created['session_id'] + '/steps?limit=2')
    assert code == 200
    page = json.loads(body)
    if page['next_cursor']:
        code, next_body = request(base, '/api/sessions/' + created['session_id'] + '/steps?limit=2&cursor=' + page['next_cursor'])
        assert code == 200
        assert not ({s['step_id'] for s in page['items']} & {s['step_id'] for s in json.loads(next_body)['items']})
    return {'status': report['status'], 'steps': report['coverage']['recognized_steps'],
            'findings': len(report['findings'])}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:8080')
    parser.add_argument('--logs-zip', help='Optional private archive; test the largest member locally')
    args = parser.parse_args()
    base = args.base_url.rstrip('/')
    assert request(base, '/api/health')[0] == 200
    assert upload(base, b'')[0] == 400
    rows = [{'type': 'user', 'uuid': 'u0', 'message': {'content': 'Run the project tests'}}]
    for n in range(3):
        rows += [
            {'type': 'assistant', 'uuid': f'c{n}', 'message': {'id': f'm{n}', 'content': [
                {'type': 'tool_use', 'id': f't{n}', 'name': 'Bash', 'input': {'command': 'npm test'}}]}},
            {'type': 'user', 'uuid': f'r{n}', 'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': f't{n}', 'is_error': True, 'content': 'Missing script: test'}]}},
        ]
    repeated = analyze(base, '\n'.join(json.dumps(r) for r in rows).encode())
    assert repeated['steps'] == 7 and repeated['findings'] > 0
    unknown = analyze(base, b'{"unrelated":123}')
    assert unknown['status'] == 'insufficient_data'
    result = {'synthetic_repeats': repeated, 'unknown_format': unknown}
    # More than 32,767 SQL parameters without batching: exercise the real DB limit.
    bulk = [{'type': 'assistant', 'uuid': f'bulk-{i}', 'message': {'content': f'Observed step {i}'}}
            for i in range(3001)]
    result['bulk_steps'] = analyze(base, '\n'.join(json.dumps(r) for r in bulk).encode())
    assert result['bulk_steps']['steps'] == 3001
    if args.logs_zip:
        with ZipFile(args.logs_zip) as archive:
            member = max((m for m in archive.infolist() if m.filename.endswith('.jsonl')), key=lambda m: m.file_size)
            result['real_log'] = analyze(base, archive.read(member))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
