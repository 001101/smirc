smirc
===

System Monitor irc (SMirc) bot to sit in IRC and report system information. Provides a locally bound zmq bind that will support streaming text to irc from the console

[![Build Status](https://travis-ci.org/epiphyte/smirc.svg?branch=master)](https://travis-ci.org/epiphyte/smirc)

# install

use the [repo](https://mirror.epiphyte.network/repos)

```
pacman -S smirc
```

or clone the dir and
```
pip install -r requirements.txt
python setup.py install
```

configure the config
```
vim /etc/epiphyte.d/smirc.json
```

# usage

## bot service

enable the systemd service
```
systemctl enable smirc
systemctl start smirc
```

bots will join the configured joint channel and a per-host specific channel

e.g. on host abc it will join (assuming joint is the name in the config)
```
#joint
#abc
```

## client

with a running bot service
```
echo "hello world" | smirc
```

## commands

anything in the json "command" dictionary are name-value pairs such that the name will be surfaced as a command `!<name>` and will execute the system command `<value>`

## modules

anything in the json "module" dictionary are name-value pairs such that name will be surfaced as a command `!<name>` and will load and execute a python module from the path

the module definition must be
```
class Module(object):

    def __init(self):
        """optional init."""
        self.var = 1
    def execute(self, connection, target, sub, log):
        """required method and signature."""
        # connection is the irc connection
        # target is the room
        # sub is any subcommands passed to by the input
        # log is a logging instance
        # <actual implementation>
        connection.privmsg(target, "hello")
```


## interacting

to see what custom commands or general abilities a bot has
```
!help
```

for a custom command
```
!customcmd arg1 arg2
```

to report status/version
```
!status
```

to restart (only works in bot private channel or by naming the bot(s) to restart)
```
# priv channel
!restart
# joint channel
!restart host-bot host2-bot
```
