"""Generation grammar shapes; fictional facts still need world validation."""
def obj(properties):
    return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}


def text():return {'type':'string'}
def texts():return {'type':'array','items':text()}
def rows(properties):return {'type':'array','items':obj(properties)}
# Pattern schemas become GBNF over the serialized JSON, not a decoded string.
# Allowing a quote/backslash/control here lets a generated name consume the
# closing quote and subsequent fields as part of its Chinese-name prefix.
NAME_PREFIX=r'[^"\\\x00-\x1f（()）]'
BILINGUAL_NAME={'type':'string','pattern':'^'+NAME_PREFIX+r"{1,80}（[A-Za-z][A-Za-z0-9 '-]{0,80}）$"}


WORLD_SCHEMA=obj({
    'title':text(),'background':text(),'rules':texts(),
    'player':obj({**{key:text() for key in ('name','species','role','background','goal')},
        'skills':texts(),'powers':rows({key:text() for key in ('name','effect','limits')}),
        'items':rows({key:text() for key in ('name','description')})}),
    'location':obj({'name':text(),'description':text(),'nearby':rows({'name':text(),'description':text()})}),
    'npc':obj({key:text() for key in ('name','species','role','description','personality','values','concern','boundary','levers','condition','priorities','appraisal','attraction','stance')}),
    'opening':text(),
})
# Keep authoring sizes consistent with build_world, rather than letting the
# model finish a large blueprint only to reject an excessive optional list.
WORLD_SCHEMA['properties']['rules'].update(minItems=1,maxItems=8)
WORLD_SCHEMA['properties']['player']['properties']['skills'].update(minItems=1,maxItems=8)
WORLD_SCHEMA['properties']['player']['properties']['powers'].update(maxItems=2)
WORLD_SCHEMA['properties']['player']['properties']['items'].update(maxItems=4)
WORLD_SCHEMA['properties']['location']['properties']['nearby'].update(maxItems=2)
WORLD_SCHEMA['properties']['player']['properties']['name']=dict(BILINGUAL_NAME)
WORLD_SCHEMA['properties']['npc']['properties']['name']=dict(BILINGUAL_NAME)
WORLD_SCHEMA['properties']['location']['properties']['name']=dict(BILINGUAL_NAME)
WORLD_SCHEMA['properties']['location']['properties']['nearby']['items']['properties']['name']=dict(BILINGUAL_NAME)
