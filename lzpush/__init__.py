import socket
import urllib
import json
import logging
import time

import socketIO_client
from datetime import datetime, timedelta
from socketIO_client import SocketIO, BaseNamespace
from socketIO_client.exceptions import SocketIOError
from socketIO_client.exceptions import ConnectionError, TimeoutError

__all__ = ['LZPush', 'PushConnection', 'NoAccessTokenError', 'PushAccessError']


logger = logging.getLogger('lzpush')
logger.setLevel(logging.ERROR)
ch = logging.StreamHandler()
logger.addHandler(ch)

socket_logger = logging.getLogger('socketIO_client')
socket_logger.setLevel(logging.ERROR)
ch = logging.StreamHandler()
socket_logger.addHandler(ch)


class NoAccessTokenError(Exception): pass
class PushAccessError(Exception): pass


class LZSocket(SocketIO):
  def wait(self, seconds=None, for_callbacks=False):
    """Wait in a loop and process events as defined in the namespaces.

    - Omit seconds, i.e. call wait() without arguments, to wait forever.
    """
    warning_screen = socketIO_client._yield_warning_screen(seconds)
    for elapsed_time in warning_screen:
      try:
        self._process_events()
      except TimeoutError, e:
        pass

      if self._stop_waiting(for_callbacks):
        break
      self.heartbeat_pacemaker.send(elapsed_time)

class PushConnection(BaseNamespace):
  def on_match_update(self, card):
    if self._on_update:
      self._on_update(card)
    else:
      logger.warning("No listener for on match update")

  def on_past_ball_update(self, ball):
    if self._on_past_ball_update:
      self._on_past_ball_update(ball)
    else:
      logger.warning("No listener for on past ball update update")

  def on_auth_failed(self, *args):
    self._raise_event('auth_failed', *args)

  def on_connect(self, *args):
    self._handler.conn_fail_count = 0
    self._connected = True
    self._connected_matches = []

    for match in self._matches:
      self._listen_match(match)  

  def on_connect_failed(self, *args):
    self._raise_event('connect_failed', *args)  
    self._connect_again()


  def on_disconnect(self, *args):
    self._raise_event('disconnect', *args)
    self._connect_again()

  def _raise_event(self, name, *args):
    logger.info("Event {}  {}".format(name, args))

    if self._on_event:
      self._on_event(name, *args)

  def _connect_again(self):    
    self._handler.reconnect()

  def _listen_match(self, match):
    logger.info("Listening to match {}".format(match))
    token = self._access_token
    self.emit('auth_match', {'match': match, 'access_token': token})


class LZPushHandler(object):

  def __init__(self, 
    access_key, secret_key, app_id, 
    device_id=None, api_endpoint=None, 
    on_update=None, on_past_ball_update=None, on_event=None):

    self.access_key = access_key
    self.secret_key = secret_key
    self.app_id = app_id
    self.device_id = device_id
    self.api_endpoint = api_endpoint or 'https://api.litzscore.com'
    self.access_token = None
    self.push_servers = None
    self.matches = []

    self.auth_fail_count = 0
    self.auth_fail_max = 30
    self.auth_retry = 1

    self.conn_fail_count = 0
    self.conn_fail_max = 30
    self.conn_retry = 1        

    self.socket = None
    self.conn = None
    self.on_update = on_update
    self.on_past_ball_update = on_past_ball_update
    self.on_event = on_event

    if self.device_id is None:      
      self.device_id = self.get_device_id()

  def get_device_id(self):
    ip = socket.gethostbyname(socket.gethostname())
    return  ip + '_' + str(time.time())

  def get_access_token(self):
    try:
      url = self.api_endpoint + '/rest/v2/auth/'
      params = dict(
        access_key = self.access_key,
        secret_key = self.secret_key,
        app_id = self.app_id,
        device_id = self.get_device_id()
      )

      params = urllib.urlencode(params)
      response = urllib.urlopen(url, data=params)
      body = response.read()
      code = response.getcode()

      self.auth_fail_count = 0
      if code == 200:
        token_info = json.loads(body)
        expires = datetime.fromtimestamp(float(token_info['auth']['expires']))

        access_token = token_info['auth']
        access_token['expires'] = expires

        if 'push_servers' not in access_token:
          raise PushAccessError("Your application do not have rights for " + \
            "Push access")

        return access_token, access_token['push_servers']
      else:
        logger.error("Bad response: " + body)
        msg = "Error getting access_token, " + \
          "please verify your access_key, secret_key and app_id"
        logger.error(msg)
        raise PushAccessError(msg)

    except IOError, e:
      logger.error("Failed to get access_token, trying again", e)

      self.auth_fail_count += 1
      if self.auth_fail_count <= self.auth_fail_max:
        time.sleep(self.auth_retry)
        return self.get_access_token()

    return None
    

  def listen_match(self, match):
    self.matches.append(match)
    if self.conn:
      self.conn.listen_match(match)

  def reconnect(self):    
    self.disconnect()
    logger.info("Connecting again")
    self.connect(self.matches, reconnect=True)

  def do_error_reconnect(self):
    self.conn_fail_count += 1
    if self.conn_fail_count <= self.conn_fail_max:
      time.sleep(self.conn_retry)
      self.reconnect()
    return None
    
  def disconnect(self):
    try:
      if self.socket:
        self.socket.disconnect()
    except Exception, e:
      pass

    logger.info("Connection closed") 

  def connect(self, matches=None, reconnect=False, wait=True):

    try:
      wait_seconds = 12 * 60 * 60
      access_token, push_servers = None, None
      if self.access_token is None:
        access_token, push_servers = self.get_access_token()
        self.access_token = access_token
        self.push_servers = push_servers

      elif self.access_token:
        access_token = self.access_token
        push_servers = self.push_servers

      if access_token is None:
        raise NoAccessTokenError

      exp = self.access_token['expires'] - timedelta(hours=8)
      now = datetime.now()
      delta = exp - now
      delta = delta.total_seconds()

      if delta > 120:
        wait_seconds = min(wait_seconds, delta)
      else:
        self.access_token = None
        self.push_servers = None          
        self.reconnect()

      if matches:
        self.matches.extend(matches)

      self.matches = list(set(self.matches))

      server = self.push_servers[0]
      logger.info("Connecting to server {}".format(server))
      self.socket = LZSocket(server['host'], int(server['port']))
      self.conn = self.socket.define(PushConnection, '/stream')

      self.conn._access_token = self.access_token['access_token']
      self.conn._on_update = self.on_update
      self.conn._on_past_ball_update = self.on_past_ball_update
      self.conn._on_event = self.on_event
      self.conn._handler = self
      self.conn._matches = self.matches

      if wait:
        try:
          logger.info("Connection started.")
          if wait_seconds:
            logger.info(
              "it will reconnect again in " + str(wait_seconds) + " seconds")

            status = self.socket.wait(wait_seconds)
          else:
            status = self.socket.wait()

          delta = exp - datetime.now()
          delta = delta.total_seconds()
          if delta < 120:
            self.reconnect()

        except KeyboardInterrupt, ke:
          self.disconnect()
          return True
      else:
        return True

      logger.info("Closing socket")

    except ConnectionError, e:
      logger.error("Failed to connect, trying again. {}".format(e))
      self.do_error_reconnect()
    except TimeoutError, te:
      logger.error("Failed to connect, trying again. {}".format(te))
      self.do_error_reconnect()

    return False





