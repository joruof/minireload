from minireload.autoreload import ModuleReloader

import os
import sys
import time
import platform
import traceback

from pydoc import locate


def launch(cls, func_name, exc_func_name=""):

    file_path = os.path.abspath(sys.modules[cls.__module__].__file__)

    cls_name = os.path.basename(file_path).rsplit(".")[0]
    cls_name += "." + cls.__qualname__

    os.environ["PYTHONPATH"] = ":".join(
            sys.path + [os.path.dirname(file_path)])

    if platform.system() == 'Windows':
        # execlpe has different semantics on Windows
        cls = locate(cls_name)
        loop(cls, func_name, exc_func_name)
    else:
        os.execlpe(sys.executable,
               "python3",
               "-m",
               "minireload.main",
               cls_name,
               func_name,
               exc_func_name,
               *sys.argv[1:],
               os.environ)


def loop(cls, func_name, exc_func_name=""):

    obj = cls()

    func = getattr(obj, func_name)
    exc_func = getattr(obj, exc_func_name, None)

    exc = None

    reloader = ModuleReloader()

    while True:
        try:
            if reloader.reload():
                exc = None

            if exc is None:
                func()
            elif exc_func is not None:
                if exc_func(exc) == True:
                    exc = None
            else:
                # backoff time to reduce cpu usage
                time.sleep(0.1)
        except KeyboardInterrupt:
            return
        except SystemExit:
            return
        except Exception as e:
            traceback.print_exc()
            exc = e
