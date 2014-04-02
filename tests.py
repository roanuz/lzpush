from lzpush import LZPushHandler

# Step 1. Call back functions 
def on_match_update(card):
  print "Got match update for", card['key']

def on_event(name, *args):
  print "Raised event %s with params %s" % (name, args)

#Step 2. Initialise handler 
lzhandler = LZPushHandler(
  access_key = 'YOUR_ACCESS_KEY',
  secret_key = 'YOUR_SECRET_KEY',
  app_id = 'YOUR_APP_ID',
  on_update = on_match_update,
  on_event = on_event
)

# Step 3. Listen matches
lzhandler.listen_match('iplt20_2013_g54')
lzhandler.listen_match('iplt20_2013_g55')

# Step 4. Connect Litzscore push server
lzhandler.connect()
