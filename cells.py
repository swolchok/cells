#TODO:
# - Make terrain work
# - Make ScalarView
# - Add more actions: PASS, LIFT, DROP,etc...
# - derive SelfView with more info than the general AgentView
# - render terrain and energy landscapes
# - fractal terrain generation
# - make rendering "smart"(and/or openGL)
# - Split into several files.
# - Messaging system
# - limit frame rate
# - response objects for outcome of action
# - Desynchronize agents

import ConfigParser
import itertools
import math
import random
import sys
import time

import numpy
import pygame

ATTACK_POWER = 20
DEATH_DROP = 25
ENERGY_CAP = 600

SPAWN_MIN_ENERGY = 50
SPAWN_COST = 20

STARTING_ENERGY = 25

config = ConfigParser.RawConfigParser()
try:
    config.read('default.cfg')
    bounds = config.getint('terrain', 'bounds')
    mind1_str = config.get('minds', 'mind1')
    mind1 = __import__(mind1_str)
    mind2_str = config.get('minds', 'mind2')
    mind2 = __import__(mind2_str)

except:
    config.add_section('minds')
    config.set('minds', 'mind2', 'mind2')
    config.set('minds', 'mind1', 'mind1')
    config.add_section('terrain')
    config.set('terrain', 'bounds', '300')

    with open('default.cfg', 'wb') as configfile:
        config.write(configfile)

    config.read('default.cfg')
    bounds = config.getint('terrain', 'bounds')

# accept command line arguments for the minds over those in the config
try:
    mind1 = __import__(sys.argv[1])
    try:
        mind2 = __import__(sys.argv[2])
    except ImportError:
        pass
except ImportError:
    pass


try:
  import psyco
  psyco.full()
except ImportError:
  pass

def signum(x):
  if x > 0:
    return 1
  if x < 0:
    return -1
  return 0


class Game:
  def __init__(self):
    self.size = self.width,self.height = (bounds,bounds)
    self.messages = [MessageQueue(), MessageQueue()]
    self.disp = Display(self.size,scale=2)
    self.time = 0
    self.tic = time.time()
    self.terr = ScalarMapLayer(self.size)
    self.terr.set_random(5)
    self.minds = [mind1.AgentMind,mind2.AgentMind]
    self.update_fields = [(x,y) for x in xrange(self.width) for y in xrange(self.height)]

    self.energy_map = ScalarMapLayer(self.size)
    self.energy_map.set_random(10)

    self.plant_map = ObjectMapLayer(self.size,None)
    self.plant_population = []

    self.agent_map = ObjectMapLayer(self.size,None)
    self.agent_population = []
    self.winner = False

    for x in xrange(7):
      mx = random.randrange(self.width)
      my = random.randrange(self.height)
      eff = random.randrange(5,11)
      p = Plant(mx, my, eff)
      self.plant_population.append(p)
      p = Plant(my, mx, eff)
      self.plant_population.append(p)
    self.plant_map.insert(self.plant_population)
    
    for idx in xrange(2):    
      (mx,my) = self.plant_population[idx].get_pos() 
      fuzzed_x = mx + random.randrange(-1,2)
      fuzzed_y = my + random.randrange(-1,2)
      self.agent_population.append(Agent(fuzzed_x, fuzzed_y, STARTING_ENERGY, idx, self.minds[idx], None))
      self.agent_map.insert(self.agent_population)

  def run_plants(self):
    for p in self.plant_population:
      (x,y) = p.get_pos()
      for dx in (-1,0,1):
        for dy in (-1,0,1):
          if self.energy_map.in_range(x+dx,y+dy):
            self.energy_map.change(x+dx,y+dy,p.get_eff())

  def add_agent(self,a):
    self.agent_population.append(a)
    self.agent_map.set(a.x, a.y, a)
  
  def del_agent(self,a):
    self.agent_population.remove(a)
    self.agent_map.set(a.x, a.y, None)
    a.alive = False
  
  def move_agent(self, a, x, y):
    self.agent_map.set(a.x, a.y, None)
    self.agent_map.set(x, y, a)
    a.x = x
    a.y = y

  def get_next_move(self,old_x, old_y, x, y):
    dx = signum(x - old_x)
    dy = signum(y - old_y)
    return (old_x + dx, old_y + dy)

  def run_agents(self):
    views = []
    self.update_fields = []
    update_fields_append = self.update_fields.append
    agent_map_get_small_view_fast = self.agent_map.get_small_view_fast
    plant_map_get_small_view_fast = self.plant_map.get_small_view_fast
    energy_map = self.energy_map
    WV = WorldView
    views_append = views.append
    for a in self.agent_population:
      update_fields_append(a.get_pos())
      x = a.x
      y = a.y
      agent_view = agent_map_get_small_view_fast(x, y)
      plant_view = plant_map_get_small_view_fast(x, y)
      world_view = WV(a, agent_view, plant_view, energy_map)
      views_append((a,world_view))
    
    #get actions
    messages = self.messages
    actions = [(a, a.act(v, messages[a.team])) for (a,v) in views]
    random.shuffle(actions)

    #apply agent actions
    for (agent,action) in actions:
      agent.energy -= 1
#      if agent.alive:
      if action.type == ACT_MOVE:
        act_x, act_y = action.get_data()
        (new_x, new_y) = self.get_next_move(agent.x, agent.y, act_x, act_y)
        if self.agent_map.in_range(new_x, new_y) and not self.agent_map.get(new_x, new_y):
          self.move_agent(agent, new_x, new_y)
      elif action.type == ACT_SPAWN:
        act_x, act_y = action.get_data()[:2]
        (new_x, new_y) = self.get_next_move(agent.x, agent.y, act_x, act_y)
        if self.agent_map.in_range(new_x, new_y) and (not self.agent_map.get(new_x, new_y)) and agent.energy >= SPAWN_MIN_ENERGY:
          agent.energy -= SPAWN_COST
          agent.energy /= 2
          a = Agent(new_x, new_y, agent.energy, agent.get_team(),self.minds[agent.get_team()], action.get_data()[2:])
          self.add_agent(a)
      elif action.type == ACT_EAT:
        intake = self.energy_map.get(agent.x, agent.y)
        agent.energy += intake
        agent.energy = min(agent.energy, ENERGY_CAP)

        self.energy_map.change(agent.x, agent.y, -intake)
      elif action.type == ACT_ATTACK:
        act_x, act_y = act_data = action.get_data()
        (new_x, new_y) = next_pos = self.get_next_move(agent.x, agent.y, act_x, act_y)
        if self.agent_map.get(act_x, act_y) and (next_pos == act_data):
          victim = self.agent_map.get(new_x, new_y)
          if agent.attack(victim):
            self.energy_map.change(new_x, new_y, DEATH_DROP)
            self.del_agent(victim)
      elif action.type == ACT_LIFT:
        if not agent.loaded and self.terr.get(agent.x, agent.y) > 0:
          agent.loaded = True
          self.terr.change(agent.x, agent.y, -1)
      elif action.type == ACT_DROP:
        if agent.loaded:
          agent.loaded = False
          self.terr.change(agent.x, agent.y, 1)

    #let agents die if their energy is too low
    team = [0, 0]
    for (agent,action) in actions:
      if agent.energy < 0 and agent.alive:
        self.energy_map.change(agent.x, agent.y, 25)
        self.del_agent(agent)
      else :
        team[agent.team] += 1
    if (team[0] == 0) :
      print "Winner is blue in: " + str(self.time)
      self.winner = True
    if (team[1] == 0) :
      print "Winner is red in: " + str(self.time)
      self.winner = True

  def tick(self):
    self.disp.update(self.terr,self.agent_population,self.plant_population,self.update_fields)
    self.disp.flip()

    self.run_agents() 
    self.run_plants() 
    for msg in self.messages:
      msg.update()
    self.time += 1
#pygame.time.wait(int(1000*(time.time()-self.tic)))
    self.tic = time.time()

class MapLayer:
  def __init__(self,size,val=0):
    self.size = self.width, self.height = size
    self.values = numpy.array([[val for x in xrange(self.width)]
                               for y in xrange(self.height)], numpy.object_)

  def get(self,x,y):
    if y >= 0 and x >= 0:
      try:
        return self.values[x,y]
      except IndexError:
        return None
    return None

  def set(self, x, y, val):
    self.values[x,y] = val
  
  def in_range(self, x, y):
    return (0 <= x < self.width and 0 <= y < self.height)


class ScalarMapLayer(MapLayer):
  def set_random(self,range):
    self.values = numpy.random.random_integers(0, range-1, (self.width, self.height)) 

  def change(self, x, y, val):
    self.values[x, y] += val


class ObjectMapLayer(MapLayer):
#   def get_view(self, x, y, r):
#     indices = [(j, k) for j in xrange(x-r, x+r+1) for k in xrange(y-r, y+r+1)
#                if 0 <= j < self.width and 0 <= k < self.height and (j != x or k != y)]
#     a = [j[0] for j in indices]
#     b = [j[1] for j in indices]
#     slc = self.values[a,b]
#     slc = [a.get_view() for a in slc if a is not None]
# #    old_way = self.old_get_view(x, y, r)
# #    assert all(type(x) == type(y) for (x,y) in itertools.izip_longest(slc, old_way)), '%s; %s' % (slc, self.old_get_view(x,y,r))
#     return slc

  def get_small_view_fast(self, x, y):
    ret = []
    get = self.get
    append = ret.append
    width = self.width
    height = self.height
    for dx in (-1, 0, 1):
      for dy in (-1, 0, 1):
        if not (dx or dy):
          continue
        try:
          adj_x = x + dx
          if not 0 <= adj_x < width:
              continue
          adj_y = y + dy
          if not 0 <= adj_y < height:
              continue
          a = self.values[adj_x, adj_y]
          if a is not None:
            append(a.get_view())
        except IndexError:
          pass
    return ret
        

  def get_view(self, x, y, r):
    ret = []
    for x_off in xrange(-r,r+1):
      for y_off in xrange(-r,r+1):
        if x_off == 0 and y_off == 0:
          continue
        a = self.get(x + x_off, y + y_off)
        if a is not None:
          ret.append(a.get_view())
    return ret

  def insert(self,list):
    for o in list:
      self.set(o.x, o.y, o)

class Agent:
  __slots__ = ['x', 'y', 'mind', 'energy', 'alive', 'team', 'loaded', 'color',
               'act']
  def __init__(self, x, y, energy, team, AgentMind, cargs):
    self.x = x
    self.y = y
    self.mind = AgentMind(cargs)
    self.energy = energy
    self.alive = True
    self.team = team
    self.loaded = False
    if team == 0:
      self.color = (255,0,0)
    else:
      self.color = (0,0,255)
    self.act = self.mind.act

  def attack(self, other):
    other.energy -= ATTACK_POWER
    return other.energy <= 0

  def get_team(self):
    return self.team

  def get_pos(self):
    return (self.x, self.y)
  
  def set_pos(self, x, y):
    self.x = x
    self.y = y
  
  def get_team(self):
    return self.team
 
  def get_view(self):
    return AgentView(self)

#def act(self,view,m):
#   return self.mind.act(view,m)

ACT_SPAWN, ACT_MOVE, ACT_EAT, ACT_ATTACK, ACT_LIFT, ACT_DROP = range(6)

class Action:
  def __init__(self,type,data=None):
    self.type = type
    self.data = data

  def get_data(self):
    return self.data
  
  def get_type(self):
    return self.type

class PlantView:
  def __init__(self,p):
    self.x = p.x
    self.y = p.y
    self.eff = p.get_eff()

  def get_pos(self):
    return (self.x, self.y)

  def get_eff(self):
    return self.eff

class AgentView:
  def __init__(self,agent):
    (self.x, self.y) = agent.get_pos()
    self.team = agent.get_team()

  def get_pos(self):
    return (self.x, self.y)

  def get_team(self):
    return self.team

class WorldView:
  def __init__(self,me,agent_views,plant_views,energy_map):
    self.agent_views = agent_views
    self.plant_views = plant_views
    self.energy_map = energy_map
    self.me = me

  def get_me(self):
    return self.me
  
  def get_agents(self):
    return self.agent_views
  
  def get_plants(self):
    return self.plant_views

  def get_energy(self):
    return self.energy_map


class Display:
  black = 0, 0, 0
  red = 255, 0, 0
  green = 0, 255, 0
  yellow = 255,255,0

  def __init__(self,size,scale=5):
    self.width, self.height = size
    self.scale = scale
    self.size = (self.width*self.scale,self.height*self.scale) 
    pygame.init()
    self.screen = pygame.display.set_mode(self.size)

  def update(self,terr,pop,plants,upfields):
    for event in pygame.event.get():
      if event.type == pygame.QUIT: 
        sys.exit()

    for f in upfields:
      (x,y)=f
      scaled_x = x * self.scale
      scaled_y = y * self.scale
      self.screen.fill((min(255,20*terr.get(x,y)),min(255,10*terr.get(x,y)),0),pygame.Rect((scaled_x,scaled_y),(self.scale,self.scale)))
    for a in pop:
      (x,y)=a.get_pos()
      x *= self.scale
      y *= self.scale
      self.screen.fill(a.color,pygame.Rect((x,y),(self.scale,self.scale)))
    for a in plants:
      (x,y)=a.get_pos()
      x *= self.scale
      y *= self.scale
      self.screen.fill(self.green,pygame.Rect((x,y),(self.scale,self.scale)))

  def flip(self):
    pygame.display.flip()

class Plant:
  def __init__(self, x, y, eff):
    self.x = x
    self.y = y
    self.eff = eff

  def get_pos(self):
    return (self.x, self.y)

  def get_eff(self):
    return self.eff

  def get_view(self):
    return PlantView(self)


class MessageQueue:
  def __init__(self):
    self.__inlist = []
    self.__outlist = []

  def update(self):
    self.__outlist = self.__inlist
    self.__inlist = []
  
  def send_message(self,m):
    self.__inlist.append(m)

  def get_messages(self):
    return self.__outlist

class Message:
  def __init__(self,message):
    self.message = message
  def get_message(self):
    return self.message

if __name__ == "__main__":
  while 1:
    game = Game()
    while not game.winner:
        game.tick()
