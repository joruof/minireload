# minireload

Small library for live code reloading of python scripts.
Basically just a nicer front-end for superreload + exception handling.
Requires only the watchdog library to check for filesystem changes.


## Setup

Available via pip:
```
pip3 install minireload
```

## Usage

As demonstrated by the code in ```example/```.

main.py
```python

from impl import main


if __name__ == "__main__":
    # Since the __main__ file cannot be reloaded by the python interpreter,
    # it just refers to another module, which contains the actual code.
    main()
```

impl.py
```
import os
import time

import minireload as mr


def update():

    print("Try changing me!")
    time.sleep(0.1)


def main():

    update_func = mr.SafeReloader([(os.path.abspath("."), True)], update)

    while True:
        update_func()
```

The update function is wrapped in a ```SafeReloader```. This reloads all
changed modules in the given paths and handles exceptions, which may happend
during live code editing.
