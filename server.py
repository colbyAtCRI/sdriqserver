#!/Users/paulcolby/env/py3/bin/python

# TODO:  need to support this message from gqrx:
# listening on port 50000
# Connected: 192.168.76.28 on port 61587
# Get Name
# Get Serial Number
# Get Unknown: [0x4] [0x20] [0x9] [0x0]


from pylibftdi.device import Device
from pylibftdi.driver import Driver
from threading import Thread, Event
from time import sleep
from socket import *
from sdrcmds import SdrIQByteCommands as bc
import numpy as np
from struct import unpack
import sys, getopt


iqDataSendHeaderSize = 4
iqDataSendBlockSize = 1024   # must be a factor of 8192; SdrDx only likes 1024
iqDataSendMsgLength = iqDataSendBlockSize + iqDataSendHeaderSize


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
    def __init__(self,output):
        self.print = output

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
        self.print(f'Unknown Message: {prnmsg(msg)}')

    def onGet(self,msg):
        self.print(f'Get {self.DataItem.get(msg[2:3],f"Unknown: {prnmsg(msg)}")}')

    def onSet(self,msg):
        self.print(f'Set {self.DataItem.get(msg[2:3],f"Unknown: {prnmsg(msg)}")}')

    def onData(self,msg):
        return

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

    # First, get the message length from the first two bytes of the message.
    msg = source(2)
    if not msg:
        return msg
    # TODO:  shouldn't the comparison really be msg[0] == 0 && (msg[1] & 0x1f) == 0 because
    #        zero length in the header means 8192?  The 3 upper bits of 0x80 is the message
    #        type (IQ data).
    if msg == b'\x00\x80':
        # This is an IQ data message with 2 header bytes and the maximum number of data bytes (8192).
        length = 8194
    else:
        # Byte 0 holds the 8 least-significant bits of the message length.
        # The lower 5 bits of byte 1 are the 5 most-significant bits.
        # TODO:  why aren't we adding 2 for the header bytes?
        length = msg[0] + (msg[1] & 0x1F) * 256

    # Read the rest of the message up to the computed length.
    while len(msg) != length:
        msg = msg + source(length-len(msg))

    return msg


class Listener:
    def __init__(self):
        self.makeItStop  = Event()
        self.warmBoot = False
        self.radioName = b'SDR-IQ'
        self.print = self.noOp
        self.boot = self.coldBoot
        self.doCommandline()
        self.findRadio()

    def doCommandline(self):
        try:
            opts, args = getopt.getopt(sys.argv[1:],'br:v')
        except getopt.GetoptError:
            print('usage: server [-b,-r <radio>, -v]')
            sys.exit(2)
        for op in opts:
            if op[0] == '-b':
                self.boot = self.noOp
            elif op[0] == '-r':
                self.radioName = bytes(op[1],encoding='utf-8')
            elif op[0] == '-v':
                self.print = print
            else:
                print(f'unknown option: {op}')

    def stop(self):
        self.makeItStop.set()

    def noOp(self,*kargs):
        return

    def coldBoot(self):
        freq = self.GetFreq()
        if (freq == 680000):
            self.print('Cold boot detected')
            self.SetDSP()
            self.SetFreq(680001)

    def findRadio(self):
        self.devices = Driver().list_devices()
        self.radio = None
        for d in self.devices:
            # ross - print('d[1]="{0}" self.radioName="{1}"'.format(d[1], self.radioName))
            if (d[1] == self.radioName.decode('utf-8')):
                self.print('found radio')
                try:
                    self.radio = Device(encoding='utf-8')
                except FtdiError as err:
                    print('Device instantiation failed:  {0}'.format(err))
        if self.radio:
            print('connected to radio')
            self.radio.flush()
            self.boot()
        else:
            print('unable to connect to radio')

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

    def serve(self):
        if not self.radio:
            print(f'Radio {self.radioName.decode()} not found')
            return
        self.tcp = socket(AF_INET,SOCK_STREAM)
        # ross 2020-06-10:  We want to accept connections from anywhere.
        # '' is equivalent to AF_ANY.
        #self.tcp.bind(('localhost',50000))
        self.tcp.bind(('',50000))
        self.tcp.listen(1)
        self.udp = socket(AF_INET,SOCK_DGRAM)
        self.udp.setsockopt(SOL_SOCKET,SO_REUSEADDR,1)
        # ross 2020-06-10:  We want to send data to anywhere
        # '' is equivalent to AF_ANY.
        #self.udp.bind(('localhost',50100))
        self.udp.bind(('',50100))
        self.print('listening on port 50000')
        try:
            self.connect = self.tcp.accept()
        except:
            # ross TODO:  print the exception
            return
        self.print(f'Connected: {self.connect[1][0]} on port {self.connect[1][1]}')
        # ross - Connected: 192.168.76.28 on port 60887
        self.writer = RadioWriter(self)
        self.reader = RadioReader(self)
        self.writer.start()
        self.reader.start()
        self.makeItStop.wait()
        self.print('closing TCP and UDP sockets')
        self.tcp.close()
        self.udp.close()
        self.print('Server - done')

class RadioWriter(Thread):
    def __init__(self,listener):
        super(RadioWriter,self).__init__()
        self.makeItStop = listener.makeItStop
        self.radio      = listener.radio
        self.tcp        = listener.connect[0]
        self.print      = listener.print
        self.logger     = Validator(listener.print)
        self.daemon     = True

    def run(self):
        # Receive messages from the SDR client and pass them on to the radio.
        while not self.makeItStop.isSet():
            msg = readMsg(self.tcp.recv)
            if not msg:
                self.makeItStop.set()
                continue
            self.logger.log(msg)    # ross - does Validator do anything other than just log shit?
            self.radio.write(msg)
        self.print('RadioWriter - done')

class RadioReader(Thread):
    def __init__(self,listener):
        super(RadioReader,self).__init__()
        self.makeItStop = listener.makeItStop
        self.tcp        = listener.connect[0]
        #self.rAddress   = ('localhost',50000)   # ross - address for sending ADC data via UDP - ? in SdrDx
        self.rAddress   = (listener.connect[1][0], 50000)   # send ADC data to the host that connected to us
        self.udp        = listener.udp          # ross - ends up being L's udp object set up in Listener::serve
        self.radio      = listener.radio
        self.print      = listener.print
        self.sequence   = 0
        self.daemon     = True

    def sequenceNumber(self):
        self.sequence = self.sequence + 1
        if (self.sequence < 0xFFFF):
            return self.sequence
        self.sequence = 1
        return self.sequence

    def sendData(self,msg):
        #self.print('sending data via UDP ({0})'.format(len(msg)))
        ba = bytearray(iqDataSendMsgLength)
        for k in range(int(len(msg) / iqDataSendBlockSize)):
            #self.print(f'  block {k}')
            sn = self.sequenceNumber()
            # TODO:  write a function that formats the 16-bit header
            #ba[0] = 0x04    # length lsb (8 bits)
            #ba[1] = 0x84    # message type 0b100 and length msb (5 bits)
            ba[0] = int(iqDataSendMsgLength) & 0xff                 # length lsb (8 bits)
            ba[1] = 0x80 | ((int(iqDataSendMsgLength) >> 8) & 0x1f)   # message type 0b100 and length msb (5 bits)
            ba[2] = sn & 0xFF
            ba[3] = (sn >> 8) & 0xFF
            ba[4:] = msg[k * iqDataSendBlockSize : (k + 1) * iqDataSendBlockSize]
            #print('k={:} 0x{:02X} 0x{:02X} 0x{:02X} 0x{:02X}'.format(k, ba[0], ba[1], ba[2], ba[3]))
            self.udp.sendto(ba,self.rAddress)  # ross - this is where we send ADC data via UDP

    def run(self):
        # Receive messages from the radio.  Send ADC data via
        # UDP and other messages via TCP to the SDR client.
        while not self.makeItStop.isSet():
            msg = readMsg(self.radio.read)
            if not msg:
                sleep(0.01)
                continue
            #ross print('got msg {0}'.format(msg))
            if msg[0:2] == b'\x00\x80':
                #print(f'power = {power(msg)}')
                #self.print('sending UDP ({0})'.format(len(msg)))
                self.sendData(msg[2:])  # ross - send ADC data
            else:
                #self.print('sending TCP ({0})'.format(len(msg)))
                self.tcp.send(msg)
        self.print('RadioReader - done')

if __name__ == '__main__':
   L = Listener()
   try:
        L.serve()
   except KeyboardInterrupt:
        print('\nbye')
