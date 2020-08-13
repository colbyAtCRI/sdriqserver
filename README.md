# This Fork
This is a fork of Paul Colby's TCP/IP server for the RFSpace SDR-IQ software-
defined radio receiver.  Significant modifications in this repo include:

* Accept connections from remote hosts
* Comments and prints to help understand how the code works

Tested on a Raspberry Pi 4 with a remote connection from SdrDx on macOS.

Below is Paul's README for the project.

# Intent
Provide a replacement for the USB to TCP/IP server, siqs_ftdi, formally provided
by the CuteSdr software bundle on Ubuntu. siqs_ftdi was need to run my SDR-IQ USB
radio with software which talks TCP/IP, like CuteSdr and SdrDdx.

[CuteSdr](https://sourceforge.net/projects/cutesdr/)
[SdrDdx](http://fyngyrz.com/?page_id=995)

## Things
The current server is specialized to the SDR-IQ though the SDR-14 and SDR-IP
might also work with small mods. The primary changes required would be to
Listener.findRadio which assumes my one and only SDR-IQ exists, and to the
cold boot feature for the SDR-IQ. When a hard reset is done, the SDR-IQ loses
all memory of the AD6620 DSP program. I detect this state by reading the
current frequency which always comes up 680000 Hz. Who knows what other radios
might do? Anyway. This warm boot can be disabled by command line switch settings

## Install
The server is written in python 3. It is highly recommended to use virtual
python environments. Reason being as one adds python libraries to the
environment one risks only screwing the environment up and not the Version
of python that make your system software run. Virtual environments can be
deleted and remade at will.

```
python3 -m venv <my-env-dir>
source <my-env-dir>/bin/activate
pip install numpy pylibftdi
```

On MacOS one will need homebrew installed. Python libraries usually wrap c or
c++ libs which will need to be installed to be called. The ones I use that
come to mind are,

libftdi
libusb

These are interdependent cause libftdi uses libusb so. On linux there is the
usual `sudo apt install libftdi`. Basically, do what it takes on your system
to get Python 3 with a working pylibftdi module.

Okay, at this point one needs to edit the first line in server.py so that it
points to your virtual python environment.

`#!<full-path-to-my-env-dir>/bin/python`

Also, the file `server.py` should be made executable
## Running
On linux or MacOS one calls up a shell and types
```
./server.py [-b][-r <radio>][-v]
```
If a radio is not plugged into USB, the server terminates. The optional
command line switches are,

`-b` for disabling the cold boot option. On power up or hard reset, the SDR-IQ
resets memory. `-b` is provided to skip the cold boot detect.

`-r <radio>` sets the radio name which will be opened. The default value for
the name is SDR-IQ. Others that might work are, SDR-IP or SDR-14 depending on
the radio being used.

`-v` selects verbose mode which prints reassuring calming helpful messages.
