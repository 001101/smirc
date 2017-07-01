smirc
===

System monitoring bot to sit in IRC and report system information

# install

use the [repo](https://mirror.epiphyte.network/repos)

```
pacman -S smirc
```

or clone the dir and
```
pip install zmq irc
python setup.py install
```

configure the config
```
vim /etc/epiphyte.d/smirc.json
```

# usage

bots will join the configured joint channel and a per-host specific channel

e.g. on host abc it will join (assuming joint is the name in the config)
```
#joint
#abc
```

