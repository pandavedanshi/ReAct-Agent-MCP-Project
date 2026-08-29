import urllib.request, json

def get(path):
    r = urllib.request.urlopen('http://127.0.0.1:8000' + path)
    return json.loads(r.read())

print('=== /api/health ===')
h = get('/api/health')
print(json.dumps(h, indent=2))

print()
print('=== /api/tools ===')
t = get('/api/tools')
print(f'Total tools: {len(t["tools"])}')
for tool in t['tools']:
    print(f'  - {tool["name"]}')

print()
print('=== /api/schema ===')
s = get('/api/schema')
for tbl in s['tables']:
    print(f'  {tbl["table"]:30s} {tbl["row_count"]} rows')

print()
print('=== POST /api/query ===')
import urllib.parse
data = json.dumps({"sql": "SELECT dept_name, COUNT(*) as students FROM students s JOIN departments d ON d.dept_id = s.dept_id GROUP BY dept_name ORDER BY students DESC", "max_rows": 10}).encode()
req = urllib.request.Request('http://127.0.0.1:8000/api/query', data=data, headers={'Content-Type': 'application/json'}, method='POST')
r = urllib.request.urlopen(req)
qr = json.loads(r.read())
print(f'Rows: {qr["row_count"]}, Index used: {qr["used_index"]}, Time: {qr["execution_ms"]} ms')
for row in qr['rows']:
    print(f'  {row}')

print()
print('ALL CHECKS PASSED')
