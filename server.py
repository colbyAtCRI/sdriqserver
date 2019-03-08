#!/Users/paulcolby/env/py3/bin/python
from pylibftdi.device import Device
from pylibftdi.driver import Driver
from queue import Queue
from threading import Thread, Event
from time import sleep
from socket import *
from sdrcmds import SdrIQByteCommands as bc
import numpy as np
from struct import unpack

def IQ(msg):
    for k in range(2,len(msg),2):
        yield unpack('h',msg[k:k+2])[0]

def power(msg):
    av = 0.0
    for iq in IQ(msg):
        av = av + iq*iq
    return av/(len(msg)-2)

def prnmsg(msg):
    return ' '.join(['['+hex(b).upper()+']' for b in msg]).replace('X','x')

class Validator:
    def __init__(self):
        self.ValidHeader = {
            b'\x04\x20' : True,
            b'\x05\x20' : True,
            b'\x05\x00' : True,
            b'\x06\x00' : True,
            b'\x08\x00' : True,
            b'\x0A\x00' : True,
            b'\x09\x00' : True,
            b'\x09\xA0' : True
        }

        self.MsgGroup = {
            b'\x20' : self.onGet,
            b'\x00' : self.onSet,
            b'\x80' : self.onData,
            b'\xa0' : self.onAD6620
        }

        self.DataItem = {
            b'\x01' : 'Name',
            b'\x02' : 'Serial Number',
            b'\x03' : 'Interface Version',
            b'\x04' : 'PIC Version',
            b'\x05' : 'Status',
            b'\x18' : 'Run/Stop',
            b'\x20' : 'Frequency',
            b'\xB0' : 'Sample Rate',
            b'\x40' : 'IF Gain',
            b'\x38' : 'RF Gain'
        }

    def log(self,msg):
        if msg[0:3] == b'\x04\x20\x05':
            return
        self.MsgGroup.get(msg[1:2],self.unknown)(msg)

    def unknown(self,msg):
        print(f'Unknown Message: {prnmsg(msg)}')

    def onGet(self,msg):
        print(f'Get {self.DataItem.get(msg[2:3],f"Unknown: {prnmsg(msg)}")}')

    def onSet(self,msg):
        print(f'Set {self.DataItem.get(msg[2:3],f"Unknown: {prnmsg(msg)}")}')

    def onData(self,msg):
        pass

    def onAD6620(self,msg):
        if msg[0] != 9:
            print(f'bogus length: {msg[0]}')
        if msg[2:3] == b'\x01':
            print('Start AD6620 Programming')
        if msg[2:3] == b'\xff':
            print('Complete AD6620 Programming')

    def valid(self,msg):
        return Validator.get(msg[0:2],False)

def readMsg(source):
    msg = source(2)
    if not msg:
        return msg
    if msg == b'\x00\x80':
        length = 8194
    else:
        length = msg[0] + (msg[1] & 0x1F)*256
    while len(msg) != length:
        msg = msg + source(length-len(msg))
    return msg

class Listener(Thread):
    def __init__(self):
        super(Listener,self).__init__()
        self.findRadio()
        self.makeItStop  = Event()
        self.abandomHope = Event()
        self.daemon = True

    def stop(self):
        self.abandomHope.set()

    def findRadio(self):
        self.devices = Driver().list_devices()
        self.radio = None
        for d in self.devices:
            if (d[1] == b'SDR-IQ'):
                self.radio = Device(encoding='utf-8')
                #self.radio.baudrate = 13200
        if self.radio:
            self.radio.flush()
            freq = self.GetFreq()
            if (freq == 680000):
                print('Cold boot detected')
                self.SetDSP()
                self.SetFreq(680001)
            #self.SetRFGain()
            #self.SetIFGain()

    def GetFreq(self):
        self.radio.write(bc.GetFreq)
        rep = readMsg(self.radio.read)
        return sum([ rep[k+5] << (8*k) for k in range(4)])

    def SetFreq(self,freq):
        msg = list(bc.SetFreq)
        for k in range(4):
            msg[k+5] = (freq >> (8*k)) & 0xFF
        self.radio.write(bytes(msg))
        return readMsg(self.radio.read)

    def SetDSP(self):
        for cmd in bc.BWKHZ_190:
            self.radio.write(cmd)
            self.radio.read(3)
        self.radio.flush()

    def SetIFGain(self):
        cmd = list(bc.SetIFGain)
        cmd[5] = 24
        self.radio.write(bytes(cmd))
        self.radio.read(5)

    def SetRFGain(self):
        cmd = list(bc.SetRFGain)
        cmd[5] = 0
        self.radio.write(bytes(cmd))

    def run(self):
        if not self.radio:
            print('no SDR-IQ found')
            return
        self.tcp = socket(AF_INET,SOCK_STREAM)
        self.tcp.bind(('localhost',50000))
        self.tcp.listen(1)
        self.udp = socket(AF_INET,SOCK_DGRAM)
        self.udp.setsockopt(SOL_SOCKET,SO_REUSEADDR,1)
        self.udp.bind(('localhost',50100))
        print('listening on port 50000')
        try:
            self.connect = self.tcp.accept()
        except:
            return
        print(f'Connected: {self.connect[1][0]} on port {self.connect[1][1]}')
        self.writer = RadioWriter(self)
        self.reader = RadioReader(self)
        self.writer.start()
        self.reader.start()
        self.makeItStop.wait()
        print('Server - done')

class RadioWriter(Thread):
    def __init__(self,listener):
        super(RadioWriter,self).__init__()
        self.makeItStop = listener.makeItStop
        self.radio      = listener.radio
        self.tcp        = listener.connect[0]
        self.logger     = Validator()
        self.daemon     = True

    def run(self):
        while not self.makeItStop.isSet():
            msg = readMsg(self.tcp.recv)
            if not msg:
                self.makeItStop.set()
                continue
            self.logger.log(msg)
            self.radio.write(msg)
        print('RadioWriter - done')

class RadioReader(Thread):
    def __init__(self,listener):
        super(RadioReader,self).__init__()
        self.makeItStop = listener.makeItStop
        self.tcp        = listener.connect[0]
        self.rAddress   = ('localhost',50000)
        self.udp        = listener.udp
        self.radio      = listener.radio
        self.sequence   = 0
        self.daemon     = True

    def sequenceNumber(self):
        self.sequence = self.sequence + 1
        if (self.sequence < 0xFFFF):
            return self.sequence
        self.sequence = 1
        return self.sequence

    def sendData(self,msg):
        ba = bytearray(1024+4)
        for k in range(4):
            sn = self.sequenceNumber()
            ba[0] = 0x04
            ba[1] = 0x84
            ba[2] = sn & 0xFF
            ba[3] = (sn>>8) & 0xFF
            ba[4:] = msg[k*1024:(k+1)*1024]
            self.udp.sendto(ba,self.rAddress)

    def run(self):
        while not self.makeItStop.isSet():
            msg = readMsg(self.radio.read)
            if not msg:
                sleep(0.01)
                continue
            if msg[0:2] == b'\x00\x80':
                #print(f'power = {power(msg)}')
                self.sendData(msg[2:])
            else:
                self.tcp.send(msg)
        print('RadioReader - done')

if __name__ == '__main__':
   L = Listener()
   L.start()
   try:
        L.join()
   except KeyboardInterrupt:
        print('\nbye')
