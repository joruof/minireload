from minireload.autoreload import ModuleReloader

import os
import sys
import time
import inspect
import platform
import traceback
import datetime

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


class ExceptionInfo:

    def __init__(self, exc):

        self.exc = exc
        self.exc_str = traceback.format_exc()
        self.exc_time = datetime.datetime.now()
        (self.exc_type, self.exc_value, self.exc_tb) = sys.exc_info()

        if isinstance(exc, SyntaxError):
            self.exc_frames = []
        else:
            self.exc_frames = inspect.getinnerframes(self.exc_tb)


def loop(cls, func_name, exc_func_name=""):

    obj = cls()

    func = getattr(obj, func_name)
    exc_func = getattr(obj, exc_func_name, None)

    exc_info = None

    reloader = ModuleReloader()

    try:
        while True:
            try:
                if reloader.reload():
                    exc_info = None

                if exc_info is None:
                    func()
                elif exc_func is not None:
                    if exc_func(exc_info):
                        exc_info = None
                else:
                    # backoff time to reduce cpu usage
                    time.sleep(0.1)
            except KeyboardInterrupt:
                break
            except SystemExit:
                break
            except Exception as e:
                traceback.print_exc()
                exc_info = ExceptionInfo(e)
    finally:
        reloader.cleanup()
