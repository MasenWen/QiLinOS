import src.memory
from src.memory.mem0_store import mem0_store

mem0_store.add([
    {'role':'user','content':'我叫张三，在北京工作'},
    {'role':'assistant','content':'好的记住了'}
])
for r in mem0_store.search('这个人叫什么'):
    print(f"[{r['score']:.2f}] {r['memory']}")


from src.memory.mem0_store import mem0_store

r = mem0_store._memory.get_all(filters={'user_id': 'nex_user'})
for item in r.get('results', [])[:3]:
    print(f"id={item['id'][:8]}...  score={item.get('score','-')} text = {item['memory']}")

mem0_store.delete_all()
