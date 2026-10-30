"""Generation grammar shapes; fictional facts still need world validation."""
def obj(properties):
    return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}


def text():return {'type':'string'}
def texts():return {'type':'array','items':text()}
def rows(properties):return {'type':'array','items':obj(properties)}
BILINGUAL_NAME={'type':'string','pattern':r"^[^（()）]+（[A-Za-z][A-Za-z0-9 '\-]{0,80}）$"}


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
AUDIT_SCHEMA=obj({'supported':{'type':'boolean'},'actors':texts(),
    'powers':rows({'actor':text(),'power':text(),'target':text()}),'issues':texts()})


def audit_schema(actor_ids):
    # Restrict generated references in the existing audit call, not a new pass.
    return obj({'supported':{'type':'boolean'},
        'actors':{'type':'array','items':{'type':'string','enum':list(actor_ids)},'minItems':1},
        'powers':rows({'actor':{'type':'string','enum':list(actor_ids)},'power':text(),
                       'target':{'type':'string','enum':list(actor_ids)}}),'issues':texts()})


def dialogue_schema(target):
    return obj({'reason':text(),'narration':text(),
        'outcome':{'type':'string','enum':['success','partial','failure']},
        'events':rows({'type':{'type':'string','enum':['npc_update']},
            'npc':{'type':'string','enum':[target]},
            'field':{'type':'string','enum':['stance']},'value':text()})})


def proposal_schema(typed_events=True):
    # Event semantics stay with the engine; every story uses the same envelope.
    def bounded(size):return {'type':'string','maxLength':size}
    def event(kind,fields):return obj({'type':{'type':'string','enum':[kind]},**fields})
    identifier=bounded(120)
    variants=[event('npc_update',{'npc':identifier,'field':{'type':'string','enum':['condition','stance']},'value':bounded(400)}),
        event('fact',{'text':bounded(600),'visibility':{'type':'string','enum':['public','private']}}),
        event('move',{'destination':identifier}),
        event('npc_move',{'npc':identifier,'from':identifier,'destination':identifier,'basis':bounded(300)}),
        event('power_use',{'actor':identifier,'power':identifier,'target':identifier}),
        event('harm',{'actor':identifier,'target':identifier,'weapon':identifier,'condition':bounded(300),
                      'fatal':{'type':'boolean'},'basis':bounded(300)})]
    return obj({'narration':bounded(700),'outcome':{'type':'string','enum':['success','failure','partial','clarify']},
        'reason':bounded(220),
        'events':{'type':'array','items':{'anyOf':variants} if typed_events else {'type':'object'},'maxItems':20}})
