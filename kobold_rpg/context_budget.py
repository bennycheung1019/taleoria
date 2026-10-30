"""Local token measurement, not another LLM or gameplay approval stage."""
import json
import urllib.parse
import urllib.request


def budget(base_url,maximum):
    if urllib.parse.urlparse(base_url).hostname not in ('localhost','127.0.0.1','::1'):return None
    for path,key in (('/api/v1/config/max_context_length','value'),('/props','n_ctx')):
        try:
            with urllib.request.urlopen(base_url.rstrip('/')+path,timeout=2) as response:data=json.load(response)
            size=data.get(key)
            if type(size) is int and size>maximum+256:return size-maximum-128
        except Exception:pass
    return None


def count(base_url,messages):
    try:
        req=urllib.request.Request(base_url.rstrip('/')+'/api/extra/tokencount',
            data=json.dumps({'messages':messages,'chat_template_kwargs':{'enable_thinking':False}}).encode(),
            headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=2) as response:data=json.load(response)
        return data.get('value') if type(data.get('value')) is int else None
    except Exception:return None
