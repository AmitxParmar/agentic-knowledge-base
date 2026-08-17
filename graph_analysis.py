import json, os

ua_dir = r'D:\projects\enterprise-agentic-knowledgebase\.understand-anything'
graph_path = os.path.join(ua_dir, 'knowledge-graph.json')

with open(graph_path) as f:
    graph = json.load(f)

proj = graph.get('project', {})
print('=== PROJECT METADATA ===')
print('name:', proj.get('name'))
print('description:', proj.get('description'))
print('languages:', proj.get('languages'))
print('frameworks:', proj.get('frameworks'))
print('analyzedAt:', proj.get('analyzedAt'))

print()
print('=== NODES MATCHING ARCHITECTURE KEYWORDS ===')
keywords = ['architecture', 'pattern', 'layer', 'pipeline', 'agent', 'retrieval', 'ingestion', 'model', 'gateway']
matched = []
for node in graph.get('nodes', []):
    name = node.get('name', '')
    summary = node.get('summary', '') or ''
    tags = node.get('tags', [])
    name_lower = name.lower()
    summary_lower = summary.lower()
    matches = [k for k in keywords if k in name_lower or k in summary_lower]
    if matches:
        matched.append(node)
        print('---')
        print('id:', node.get('id'))
        print('name:', name)
        print('type:', node.get('type'))
        print('tags:', tags)
        s = summary[:200] if len(summary) > 200 else summary
        print('summary:', s)

print()
print('=== LAYERS ===')
for layer in graph.get('layers', []):
    print('layer:', layer.get('id'), '-', layer.get('name'))
    desc = layer.get('description', '')[:100] if layer.get('description') else ''
    print('  description:', desc)

print()
print('=== SUMMARY ===')
print('Total nodes:', len(graph.get('nodes', [])))
print('Total edges:', len(graph.get('edges', [])))
print('Total layers:', len(graph.get('layers', [])))
print('Matched architecture nodes:', len(matched))

# Print all matched node IDs
print()
print('=== MATCHED NODE IDs ===')
for n in matched:
    print('  ', n.get('id'))