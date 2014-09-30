from lzpush import LZPushHandler

access_key = ''
secret_key = ''
app_id = ''
matches = []


# Step 1. Call back functions 
def on_match_update(card):
  n = card['now']
  if 'req' in n and 'runs' in n['req']:
    print "%s - %s(%s)" % (n['runs_str'], n['req']['runs'], n['req']['balls'])
  else:
    print "%s" % (n['runs_str'])

  # print "Got match update for", card['key'],

def on_event(name, *args):
  print "Raised event %s with params %s" % (name, args)

# Step 2. Initialise handler 
lzhandler = LZPushHandler(
  access_key = access_key,
  secret_key = secret_key,
  app_id = app_id,
  on_update = on_match_update,
  on_event = on_event
)


# Step 3. Listen matches
for match in matches:
  lzhandler.listen_match(match)

# Step 4. Connect Litzscore push server
lzhandler.connect()
