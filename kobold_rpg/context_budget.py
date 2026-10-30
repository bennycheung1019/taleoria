"""Local token measurement, not another LLM or gameplay approval stage."""
import json
import urllib.parse
import urllib.request


def budget(base_url,maximum):
    if urllib.parse.urlparse(base_url).hostname not in ('localhost','127.0.0.1','::1'):return None
    try:
        with urllib.request.urlopen(base_url.rstrip('/')+'/props',timeout=2) as response:props=json.load(response)
        size=props.get('n_ctx')
        return size-maximum-128 if type(size) is int and size>maximum+256 else None
    except Exception:return None


def count(base_url,messages):
    try:
        req=urllib.request.Request(base_url.rstrip('/')+'/api/extra/tokencount',
            data=json.dumps({'messages':messages,'chat_template_kwargs':{'enable_thinking':False}}).encode(),
            headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=2) as response:data=json.load(response)
        return data.get('value') if type(data.get('value')) is int else None
    except Exception:return None
