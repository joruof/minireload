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
```python
import time

import minireload as mr


def update():

    print("Try changing me!")
    time.sleep(0.1)

    return 42


def main():

    enable_autoreload = True

    if enable_autoreload:
        func = mr.WrappingReloader(update)
    else:
        func = update

    while True:
        res = func()

        if type(res) == mr.ReloadErrorInfo:
            print("Everything is awful:", res)
        else:
            print("Everything is awesome:", res)
```

The update function is wrapped in a ```WrappingReloader```. By default this
reloads the toplevel module the function belongs to and handles exceptions,
which may happen during live code editing.
