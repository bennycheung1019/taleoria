"""KoboldCpp completion transport and strict JSON response parser."""
import json
import re
import urllib.request
from .engine import RuleError
from .progress import active

class InvalidJSONError(RuleError):
    pass


def parse_proposal(text):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('duplicate JSON key')
            result[key]=value
        return result
    def decode(value):
        return json.loads(value,object_pairs_hook=pairs,
                          parse_constant=lambda value:(_ for _ in ()).throw(ValueError(value)))
    try:
        if not isinstance(text,str):raise TypeError('missing text')
        text=text.strip()
        if text.startswith('```') and text.endswith('```'):
            text=re.sub(r'^```(?:json)?\s*','',text,flags=re.I)[:-3].strip()
        try:
            result=decode(text)
        except ValueError:
            # Some backends ignore response_format. Recover one whole object,
            # never an inner fragment, two competing results or damaged JSON.
            stack=[];quoted=False;escaped=False;start=None;candidates=[]
            for index,char in enumerate(text):
                if not stack:
                    if char in '{[':start=index;stack.append(char)
                    continue
                if quoted:
                    if escaped:escaped=False
                    elif char=='\\':escaped=True
                    elif char=='"':quoted=False
                    continue
                if char=='"':quoted=True
                elif char in '{[':stack.append(char)
                elif char in '}]':
                    if stack[-1] != ('{' if char=='}' else '['):raise ValueError('unbalanced JSON')
                    stack.pop()
                    if not stack:candidates.append(decode(text[start:index+1]))
            if stack or len(candidates)!=1:raise ValueError('not one complete result')
            result=candidates[0]
        if not isinstance(result,dict):raise ValueError('result must be an object')
        return result
    except (ValueError, TypeError) as exc:
        raise InvalidJSONError('這次回覆的資料未完整，行動尚未執行，故事進度已保留。請再試一次。') from exc


def _complete(messages, base_url, max_tokens, temperature, timeout=100,response_schema=None,raw=False):
    progress=active.get()
    payload = {"model": "koboldcpp", "messages": messages,
               "temperature": temperature, "max_tokens": max_tokens, "stream": bool(progress),
               "chat_template_kwargs": {"enable_thinking": False}, "reasoning_effort": "none"}
    payload['response_format']={'type':'json_schema','json_schema':{'name':'taleoria_response','strict':True,
        'schema':response_schema if response_schema is not None else {'type':'object'}}}
    if progress:
        perf={}
        try:
            with urllib.request.urlopen(base_url+'/api/extra/perf',timeout=2) as response:perf=json.load(response)
        except Exception:pass
        progress.begin(max_tokens,messages,perf)
    req = urllib.request.Request(base_url + "/v1/chat/completions", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if progress and 'text/event-stream' in response.headers.get('Content-Type',''):
                pieces=[];finished=False
                for line in response:
                    if not line.startswith(b'data:'):continue
                    data=line[5:].strip()
                    if data==b'[DONE]':finished=True;break
                    chunk=json.loads(data)
                    for choice in chunk.get('choices',[]):
                        content=choice.get('delta',{}).get('content')
                        if content:pieces.append(content);progress.fragment()
                        if choice.get('finish_reason') is not None:finished=True
                if not finished:raise ValueError('Incomplete generation stream')
                text=''.join(pieces)
            else:
                result=json.load(response);text=result['choices'][0]['message']['content']
    except Exception as exc:
        raise RuleError("KoboldCpp 沒有提供可用回應；世界狀態未變。請確認它在 localhost:5001 運行。") from exc
    result=text if raw else parse_proposal(text)
    if progress:progress.call_done()
    return result
