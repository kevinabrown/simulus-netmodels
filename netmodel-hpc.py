

''' HPC-like network with credit-based flow control.
    Currently uses static routing table for streaming incast traffic.

    Notes:
    - Use the DEBUG variable to increase/decrease logging
'''

import simulus
from collections import deque
from random import seed, expovariate, uniform
from pprint import pprint

seed(12345)

DEBUG = 1
TRACK_CREDITS = False

routers   = [0]
receivers = [1]
senders   = [2, 3]

# static routing table for finding path through the network
routing_table = {0:     # nodeid
                 {1: 1, # dst : next_hop
                  2: 2,
                  3: 3},
                1:
                 {},
                2:
                 {1: 0},
                3:
                 {1: 0}
                }

all_nodes = []
all_nodes.extend(routers)
all_nodes.extend(senders)
all_nodes.extend(receivers)

# set single reciever for incast
incast_dst = receivers[0]

injection_delay = 0.5   # based on port bandwidth (line rate)
link_delay = 2          # based on link propogation delay
buffer_size = 15

packet_gen_cnt = 0

def packet_generator(nodeid):
    global packet_gen_cnt
    global outputbuffers
    # generates and buffers a new packets after a random delay
    # WARNING: This appends to unbounded buffers
    while True:
        # generate packet
        packet = {'packetid': packet_gen_cnt, 'srcid': nodeid, 'dstid': incast_dst,
                           'last_hop': nodeid, 'packet_size': 1}

        # add to buffer
        outputbuffers[nodeid].appendleft(packet.copy())
        sem_used_buff[nodeid].signal()

        if DEBUG > 1:
            print("Node[%d] generated packet %d at Time:%g"
                  % (nodeid, packet_gen_cnt, sim.now))

        packet_gen_cnt += 1
        # sleep
        sim.sleep(.5)

# This is really the LP for a single output port of a node and not the entire node
def node(mynodeid):
    while True:
        # check buffer has packet
        sem_used_buff[mynodeid].wait()

        # If this is a reciever, remove packet and continue
        if mynodeid in receivers:
            packet = outputbuffers[mynodeid].pop()

            # return credit upstream
            sim.sched(recieve_credit, mynodeid, packet['last_hop'], offset = link_delay)

            if DEBUG > 0:
                print("Node[%d] recieved packet %d from node %d via %d at Time:%g"
                      % (mynodeid, packet['packetid'], packet['srcid'], packet['last_hop'], sim.now))
            continue

        # get next hop (this is currently a hardcoded static routing)
        dstid = outputbuffers[mynodeid][-1]['dstid']
        last_hop = outputbuffers[mynodeid][-1]['last_hop']
        next_hop = routing_table[mynodeid][dstid]

        # check we have credit to send
        sem_free_buff[mynodeid][next_hop].wait()

        # decrement credit counter for the credit we will use to send
        use_credit(mynodeid, next_hop)

        # start sending: inject packet after delay (based on line rate)
        sim.sleep(injection_delay)
        packet = outputbuffers[mynodeid].pop()

        # complete sending: schedule packet arrival at next hop
        packet['last_hop'] = mynodeid
        sim.sched(recieve_packet, next_hop, packet, offset = link_delay)

        if DEBUG > 1:
            print("Node[%d] sending packet %d to next_hop %d at Time:%g"
                  % (mynodeid, packet['packetid'], next_hop, sim.now))

        # return credit upstream if this isn't originating node
        if mynodeid != last_hop:
            sim.sched(recieve_credit, mynodeid, last_hop, offset = link_delay)


def recieve_packet(recvid, packet):
    # add to packet to buffer
    outputbuffers[recvid].appendleft(packet.copy())
    sem_used_buff[recvid].signal()


def recieve_credit(mynodeid, last_hop): # recieve credit from a downstream node
    sem_free_buff[last_hop][mynodeid].signal()
    credit_counters[last_hop][mynodeid] += 1

    if TRACK_CREDITS:
        print("CRDT: %d-%d %.2f %d" %(last_hop, mynodeid, sim.now, credit_counters[last_hop][mynodeid]))

def use_credit(mynodeid, next_hop): # decrement local credit counter
    credit_counters[mynodeid][next_hop] -= 1

    if TRACK_CREDITS:
        print("CRDT: %d-%d %.2f %d" %(mynodeid, next_hop, sim.now, credit_counters[mynodeid][next_hop]))

sim = simulus.simulator()

# list of output buffers
outputbuffers = []

# setup processes, semaphores, and buffers
for nodeid in range(len(all_nodes)):
    if nodeid in senders:
        sim.process(packet_generator, nodeid, until=0)
    sim.process(node, nodeid, until = 10)

    outputbuffers.append( deque() )

# credit_counters[mynodeid][next_hop]: counter for credits held by mynodeid for next_hop node
credit_counters = {}

# Semaphores for synchronizations
sem_free_buff = {}  # available slots
sem_used_buff = {}  # occupied slots

for nodeid in routing_table.keys():
    credit_counters[nodeid] = {}
    sem_free_buff[nodeid] = {}
    sem_used_buff[nodeid] = sim.semaphore(0)

    for next_hop in set(routing_table[nodeid].values()): # get unique next hops
        credit_counters[nodeid][next_hop] = buffer_size
        sem_free_buff[nodeid][next_hop] = sim.semaphore(buffer_size)

        if DEBUG > 2:
            print("Created credit couter for node:%d next_hop:%d"
                  % (nodeid, next_hop))

sim.run(30)

