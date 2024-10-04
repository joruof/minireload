import os
import gc
import sys
import time
import inspect
import datetime
import threading
import traceback

from contextlib import contextmanager

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from minireload.autoreload import superreload


def get_toplevel_module_path(obj):

    module_name = obj.__module__.split(".")[0]
    module_spec = sys.modules[module_name].__spec__
    if module_spec is None:
        if module_name == "__main__":
            raise RuntimeError('the __main__ module cannot be reloaded')
        else:
            raise RuntimeError(f'could not find __spec__ of module {module_name}')
    module_origin = module_spec.origin
    module_path = os.path.dirname(os.path.abspath(module_origin))

    return module_path


class ReloadEventHandler(FileSystemEventHandler):

    def __init__(self):

        self.lock = threading.Lock()
        self.reload_set = set()

    def pop_reload_set(self):

        with self.lock:
            rl = self.reload_set
            self.reload_set = set()

        return rl

    def on_any_event(self, event):

        if event.is_directory:
            return

        if event.event_type not in ["modified", "moved", "created"]:
            return

        with self.lock:
            if event.src_path not in self.reload_set:
                self.reload_set.add(event.src_path)


class ReloadErrorInfo(Exception):

    def __init__(self, exc):

        self.exc = exc
        self.exc_str = traceback.format_exc()
        self.exc_time = datetime.datetime.now()
        (self.exc_type, self.exc_value, self.exc_tb) = sys.exc_info()

        if isinstance(exc, SyntaxError):
            self.exc_frames = []
        else:
            self.exc_frames = inspect.getinnerframes(self.exc_tb)


class Reloader:

    def __init__(self, reload_paths: list[tuple[str, bool]]):

        self.event_handler = ReloadEventHandler()

        self.observers = []
        for path, recursive in reload_paths:
            if not os.path.isabs(path):
                raise ValueError(f'reload path "{path}" must be an absolute path')
            observer = Observer()
            observer.schedule(self.event_handler, path, recursive=True)
            observer.start()

        self.reloaded_modules = []

        # needed for superreload
        self.old_objects = {}

    def reload(self):
        """
        Reloads all modified modules under the specified reload_paths.

        Returns True if at least one module was reloaded and False otherwise.
        """

        reload_set = self.event_handler.pop_reload_set()

        if len(reload_set) == 0:
            return False

        self.reloaded_modules = []

        for name, m in sys.modules.items():
            try:
                origin = m.__spec__.origin
            except AttributeError:
                continue

            # defer the reload because it may modify sys.modules
            if origin in reload_set:
                self.reloaded_modules.append(m)

        for m in self.reloaded_modules:
            superreload(m, old_objects=self.old_objects)

        # important: do a garbage collection run after every reload
        # clears out old objects and reduces subsequent reload runtimes
        gc.collect()

        return True


class WrappingReloader(Reloader):
    """
    Wraps a given function and, if necessary, reloads it on every invocation.
    By default, the entire toplevel module, to which func belongs, is reloaded.

    Exceptions raised during the execution of the function will be caught.
    In case of a caught exception a ReloadErrorInfo object will be returned
    instead of the return value of the function.
    """

    def __init__(self,
                 func,
                 reload_paths: list[tuple[str, bool]] = None,
                 retry_after_secs=0.1):

        if reload_paths is None:
            reload_paths = [(get_toplevel_module_path(func), True)]

        super().__init__(reload_paths)

        self.func = func
        self.retry_after_secs = retry_after_secs

        self.exc_info = None

    def __call__(self, *args, **kwargs):

        try:
            if self.reload():
                self.exc_info = None

            if self.exc_info is None:
                return self.func(*args, **kwargs)
            else:
                time.sleep(self.retry_after_secs)
                return self.exc_info
        except KeyboardInterrupt as e:
            raise e
        except SystemExit as e:
            raise e
        except Exception as e:
            traceback.print_exc()
            self.exc_info = ReloadErrorInfo(e)
            return self.exc_info


def launch(cls, func_name, exc_func_name=""):
    """
    Legacy launch function for compatiblity with older versions.

    Instantiates cls, and executes func in a while loop with live reloading.
    If an error was raised exc_func will be executed instead.

    cls: class, can be initialized without any arguments
    func_name: name of function of cls to be executed
    exc_func_name: name of function of cls to be executed in case of error
    """

    obj = cls()

    func = getattr(obj, func_name)
    exc_func = getattr(obj, exc_func_name, None)

    reloader = WrappingReloader(func)

    while True:
        res = reloader()
        if exc_func_name is not None and type(res) == ReloadErrorInfo:
            exc_func(res)
