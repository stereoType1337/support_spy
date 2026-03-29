docker exec support-redis-ray redis-cli -n 1 HVALS users 2>/dev/null | python3 -c "
import sys, json
max_tid = 0
total = 0
for line in sys.stdin:
    try:
        d = json.loads(line.strip());
        total += 1
        tid = d.get('message_thread_id') or 0
        if tid > max_tid: max_tid = tid
    except:
        pass
print(f'DB1 — Total: {total}, Max thread_id: {max_tid}')
"
docker exec support-bot-ray python -c "import os; os.environ['REDIS_HOST'] = 'support-redis-ray'; exec(open('/usr/src/app/scripts/migrate_redis_to_postgres.py').read())"