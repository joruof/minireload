# minireload

Hot code reloading for python scripts with a main loop.
Basically just a nicer front-end for superreload + exception handling.
Requires only the python standard library and no external dependencies. 


## Setup

Available via pip:
```
pip3 install minireload
```

## Usage

```python
import minireload as mr

class Main:

    def do_update(self):
        """
        This function will be called in a while loop. Do your wörk here!
        """

        work()
        work()
        work()

    def handle_exc(self, exc):
        """
        If an exception occured during execution or reload, minireload tries to
        call this function, allowing the user to define custom exception handling.
        """

        print('Help!')

if __name__ == '__main__':
    mr.launch(Main, 'do_update', exc_func_name='handle_exc')
```
